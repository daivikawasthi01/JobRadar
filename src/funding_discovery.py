"""Discover recently funded Indian startups from funding-news RSS feeds.

Sources (public RSS feeds; robots.txt allows them):
- Entrackr `https://entrackr.com/rss`: one headline per deal, e.g.
  "Space robotics startup Cosmochute raises $1.5 Mn in pre-seed round".
- Inc42 `https://inc42.com/buzz/feed/`: single-deal headlines, plus the weekly
  "Funding Galore" article whose full HTML (in `content:encoded`) has a deal table
  with Name / Funding Round Size / Funding Round Type columns.

Discovery input only: only company names, round, and amount are kept. Never creates
Job records. Feeds hold only the last few days, so run this daily to build history.
"""
import asyncio
import csv
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import logging
from pathlib import Path
import re
from datetime import timezone
import xml.etree.ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup

from src.discovery import normalize_company_name
from src.registry import CompanyMeta, load_company_meta, upsert_company_meta

logger = logging.getLogger("jobradar.funding_discovery")

FEEDS = {
    "entrackr": "https://entrackr.com/rss",
    "inc42": "https://inc42.com/buzz/feed/",
}
USER_AGENT = "JobRadar/1.0 (company discovery)"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
INPUT_HEADER = ["name", "website", "segment", "stage", "amount_usd_mn", "sector", "published", "source", "link"]
USD_PER_CRORE_MN = 0.115  # approx. Rs 1 Cr in USD millions, only used to bucket round size

RE_STAGE = re.compile(
    r"\b(pre[- ]seed|seed|angel|pre[- ]series\s+[a-h]|series\s+[a-h])\b", re.IGNORECASE
)
RE_AMOUNT = re.compile(
    r"(?P<cur>\$|usd\s*|rs\.?\s*|inr\s*|₹\s*)(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>mn|million|m|cr|crore|bn|billion|lakh\s*cr)\b",
    re.IGNORECASE,
)
# "<company> raises ...", "<company> nets ...", "<company> tops up ..."
RE_COMPANY_VERB = re.compile(
    r"^(?P<company>.+?)\s+(?:raises|raised|nets|bags|secures|closes|picks up|lands|receives|"
    r"mops up|scoops up|tops up|kicks off|gets)\b\s+(?P<rest>.*)$",
    re.IGNORECASE,
)
# "<investor> leads $12.5 Mn Series A round in <company>", "<investor> backs <company> with ..."
RE_INVESTOR_LEADS = re.compile(
    r"\b(?:leads|co-leads|led)\b.*?\bround\s+in\s+(?P<company>.+?)\s*$", re.IGNORECASE
)
RE_INVESTOR_BACKS = re.compile(r"\bbacks\s+(?P<company>.+?)\s+with\b", re.IGNORECASE)
# Descriptor words before the name: "Enterprise AI startup RapidCanvas", "Toothsi parent MakeO".
RE_DESCRIPTOR = re.compile(
    r"^.*\b(?:startup|start-up|platform|brand|marketplace|company|firm|maker|player|"
    r"provider|app|parent|unicorn|fintech|edtech|healthtech|saas)\s+(?=\S)",
    re.IGNORECASE,
)
# Headlines that mention money but are not a startup's own round.
RE_SKIP = re.compile(
    r"\b(ipo|drhp|anchor investors?|this week|debt|revenue|profit|loss|"
    r"decoding|plans|to consider|clears plans|board)\b|^from\s.+\bto\b"
    # A VC raising its own fund ("raises Rs 3,000 Cr for growth-stage AI fund"),
    # not a lead investor named "... Fund".
    r"|\bfor\b.*\bfunds?\b|\b(?:new|maiden|debut)\s+fund\b|\bfund\s+(?:[ivx]+|\d+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Deal:
    name: str
    stage: str              # raw round text, e.g. "Series A", "" if unknown
    amount_usd_mn: float | None
    sector: str
    published: str          # ISO date YYYY-MM-DD, "" if unknown
    source: str             # feed name
    link: str

    @property
    def segment(self) -> str:
        return stage_to_segment(self.stage, self.amount_usd_mn)


def stage_to_segment(stage: str, amount_usd_mn: float | None) -> str:
    """Map a round name to a segment; fall back to round size when no round is named.

    Size buckets (estimate): <=$5 Mn seed, <=$20 Mn Series A, <=$50 Mn Series B, else C+.
    """
    s = (stage or "").lower().replace("-", " ")
    if re.search(r"\b(pre seed|seed|angel)\b", s):
        return "seed"
    m = re.search(r"series\s+([a-h])\b", s)
    if m:
        return {"a": "series_a", "b": "series_b"}.get(m.group(1), "series_c_plus")
    if amount_usd_mn is None:
        return "unknown"
    if amount_usd_mn <= 5:
        return "seed"
    if amount_usd_mn <= 20:
        return "series_a"
    if amount_usd_mn <= 50:
        return "series_b"
    return "series_c_plus"


def parse_amount(text: str) -> float | None:
    """Return the first money amount in USD millions ("$29 Mn", "Rs 255 Cr", "₹109 Cr")."""
    m = RE_AMOUNT.search(text or "")
    if not m:
        return None
    value = float(m.group("num").replace(",", ""))
    unit = m.group("unit").lower().replace(" ", "")
    usd = m.group("cur").strip().lower() in {"$", "usd"}
    if unit in {"bn", "billion"}:
        value *= 1000
    elif unit == "lakhcr":
        value *= 100000
    if unit in {"cr", "crore", "lakhcr"} or not usd:
        if unit in {"mn", "million", "m"}:  # "Rs 50 Mn" is rare; treat as INR millions
            return round(value * USD_PER_CRORE_MN / 10, 3)
        return round(value * USD_PER_CRORE_MN, 3)
    return value


def _clean_company(raw: str) -> str | None:
    name = re.sub(r"^(?:exclusive|update|\[update\])\s*:?\s*", "", raw.strip(), flags=re.IGNORECASE)
    name = RE_DESCRIPTOR.sub("", name).strip(" ,:'\"‘’“”-–—")
    name = re.sub(r"[’']s$", "", name).strip()
    words = name.split()
    if not words or len(words) > 5 or not re.match(r"[A-Za-z0-9]", name):
        return None
    return name


def parse_headline(title: str) -> tuple[str, str, float | None] | None:
    """Extract (company, stage, amount_usd_mn) from a single-deal funding headline."""
    title = " ".join((title or "").split())
    if not title or RE_SKIP.search(title):
        return None
    company = None
    m = RE_INVESTOR_LEADS.search(title) or RE_INVESTOR_BACKS.search(title)
    if m:
        company = _clean_company(m.group("company"))
    else:
        m = RE_COMPANY_VERB.match(title)
        if m and (RE_AMOUNT.search(m.group("rest")) or RE_STAGE.search(m.group("rest"))):
            company = _clean_company(m.group("company"))
    if not company:
        return None
    stage_m = RE_STAGE.search(title)
    return company, (stage_m.group(1) if stage_m else ""), parse_amount(title)


def parse_deal_table(html: str) -> list[dict]:
    """Rows of an Inc42 Funding Galore table: name, stage, amount, sector."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict] = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [c.get_text(" ", strip=True).lower() for c in trs[0].find_all(["th", "td"])]
        if "name" not in header or not any("round type" in h for h in header):
            continue
        col = {h: i for i, h in enumerate(header)}
        type_i = next(i for h, i in col.items() if "round type" in h)
        size_i = next((i for h, i in col.items() if "round size" in h), None)
        sector_i = col.get("sector")
        for tr in trs[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= max(col["name"], type_i):
                continue
            name = cells[col["name"]].strip()
            if not name:
                continue
            stage = cells[type_i] if RE_STAGE.search(cells[type_i]) else ""
            rows.append({
                "name": name,
                "stage": stage,
                "amount_usd_mn": parse_amount(cells[size_i]) if size_i is not None and size_i < len(cells) else None,
                "sector": cells[sector_i] if sector_i is not None and sector_i < len(cells) else "",
            })
    return rows


def _published(item: ET.Element) -> str:
    raw = item.findtext("pubDate") or ""
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def parse_feed(xml_text: str, source: str) -> list[Deal]:
    """Parse one RSS feed into deals. Malformed items are skipped."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("Could not parse %s feed: %s", source, exc)
        return []
    deals: list[Deal] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = _published(item)
        for row in parse_deal_table(item.findtext(CONTENT_NS) or ""):
            deals.append(Deal(row["name"], row["stage"], row["amount_usd_mn"], row["sector"], published, source, link))
        parsed = parse_headline(title)
        if parsed:
            name, stage, amount = parsed
            deals.append(Deal(name, stage, amount, "", published, source, link))
    return deals


def merge_deals(existing: list[dict], deals: list[Deal]) -> list[dict]:
    """Accumulate deals by normalized name, keeping the most recent round per company."""
    by_key: dict[str, dict] = {}
    for row in existing:
        key = normalize_company_name(row.get("name", ""))
        if key:
            by_key[key] = row
    for deal in deals:
        key = normalize_company_name(deal.name)
        if not key:
            continue
        old = by_key.get(key)
        if old and (old.get("published") or "") > deal.published:
            continue
        if old and old.get("published") == deal.published and old.get("stage") and not deal.stage:
            continue  # same day: keep the record that names the round
        by_key[key] = {
            "name": deal.name,
            "website": (old or {}).get("website", ""),
            "segment": deal.segment,
            "stage": deal.stage,
            "amount_usd_mn": "" if deal.amount_usd_mn is None else f"{deal.amount_usd_mn:g}",
            "sector": deal.sector or (old or {}).get("sector", ""),
            "published": deal.published,
            "source": deal.source,
            "link": deal.link,
        }
    return sorted(by_key.values(), key=lambda r: (r.get("published") or "", r["name"].casefold()), reverse=True)


def read_inputs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_inputs(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INPUT_HEADER, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def meta_rows(rows: list[dict], existing: dict[str, CompanyMeta]) -> list[CompanyMeta]:
    """Funding stage wins over a headcount estimate; known team size is kept."""
    out = []
    for row in rows:
        old = existing.get(normalize_company_name(row["name"]))
        out.append(CompanyMeta(
            name=old.name if old else row["name"],
            segment=row["segment"] or "unknown",
            team_size=old.team_size if old else None,
            hq_country=(old.hq_country if old and old.hq_country else "India"),
            source=f"funding:{row['source']}:{row['published']}",
        ))
    return out


async def _fetch(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def run_funding_discovery(
    inputs_path: str = "config/inputs/funding_news.csv",
    meta_path: str = "config/company_meta.csv",
) -> tuple[int, int, int]:
    """Fetch the feeds, accumulate deals, and update metadata.

    Returns (deals parsed this run, companies in the input file, metadata rows changed).
    One feed failing does not stop the other.
    """
    deals: list[Deal] = []
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        for source, url in FEEDS.items():
            try:
                deals.extend(parse_feed(await _fetch(session, url), source))
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Could not fetch %s feed: %s", source, exc)
    path = Path(inputs_path)
    rows = merge_deals(read_inputs(path), deals)
    write_inputs(rows, path)
    changed = upsert_company_meta(meta_path, meta_rows(rows, load_company_meta(meta_path)))
    return len(deals), len(rows), changed
