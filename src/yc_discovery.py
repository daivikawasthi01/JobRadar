"""Import India-region Y Combinator companies as discovery input and company metadata.

Source: the open yc-oss dataset (static JSON on GitHub Pages, built from YC's public
directory). Discovery input only: this never creates Job records.
"""
import asyncio
import csv
import logging
from pathlib import Path

import aiohttp

from src.registry import CompanyMeta, estimate_segment, upsert_company_meta

logger = logging.getLogger("jobradar.yc_discovery")

YC_COMPANIES_URL = "https://yc-oss.github.io/api/companies/all.json"
USER_AGENT = "JobRadar/1.0 (company discovery)"
KEPT_STATUSES = {"Active", "Public"}


class YCDiscoveryError(Exception):
    """Raised when the YC dataset cannot be processed."""


def select_india_companies(data: object) -> list[dict]:
    """Return active or public YC companies whose regions include India."""
    if not isinstance(data, list):
        raise YCDiscoveryError("YC dataset is not a list of companies.")
    selected = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        regions = item.get("regions") or []
        if not isinstance(name, str) or not name.strip():
            continue
        if item.get("status") not in KEPT_STATUSES or "India" not in regions:
            continue
        selected.append(item)
    return selected


def hq_country(all_locations: str | None) -> str:
    """First listed location decides HQ: 'India' or 'other'."""
    first = (all_locations or "").split(";")[0]
    return "India" if "india" in first.lower() else "other"


def company_meta_from_yc(item: dict) -> CompanyMeta:
    team_size = item.get("team_size") if isinstance(item.get("team_size"), int) else None
    segment = "large" if item.get("status") == "Public" else estimate_segment(team_size)
    return CompanyMeta(
        name=item["name"].strip(),
        segment=segment,
        team_size=team_size,
        hq_country=hq_country(item.get("all_locations")),
        source=f"yc:{item.get('batch') or ''}".rstrip(":"),
    )


def write_inputs(companies: list[dict], path: Path) -> None:
    """Write a `name,website` CSV that `discover` reads from config/inputs/."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "website"])
        for item in sorted(companies, key=lambda c: c["name"].casefold()):
            writer.writerow([item["name"].strip(), (item.get("website") or "").strip()])


async def fetch_yc_companies(session: aiohttp.ClientSession) -> object:
    async with session.get(YC_COMPANIES_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def run_yc_discovery(
    inputs_path: str = "config/inputs/yc_india.csv",
    meta_path: str = "config/company_meta.csv",
) -> tuple[int, int]:
    """Refresh the YC India input file and metadata. Returns (companies, meta rows written)."""
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
            data = await fetch_yc_companies(session)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise YCDiscoveryError(f"Could not download the YC dataset: {exc}") from exc
    companies = select_india_companies(data)
    write_inputs(companies, Path(inputs_path))
    written = upsert_company_meta(meta_path, [company_meta_from_yc(c) for c in companies])
    return len(companies), written
