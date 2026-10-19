"""Company discovery and slug probing pipeline for JobRadar."""
import asyncio
import csv
import json
import logging
from pathlib import Path
import re
import shutil
import string
import sys
import time
from urllib.parse import urlparse
import urllib.robotparser
import aiohttp
from src.adapters import ADAPTERS
from src.fetcher import NotFoundError
from src.filters import detect_country
from src.models import Company, Job

logger = logging.getLogger("jobradar.discover")

TRAILING_WORDS = {
    "inc", "llc", "ltd", "limited", "pvt", "private", "corp",
    "corporation", "co", "technologies", "technology", "labs", "software"
}

RE_GH_LINK = re.compile(
    r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)",
    re.IGNORECASE,
)
RE_LEVER_LINK = re.compile(
    r"jobs\.lever\.co/([a-z0-9_-]+)",
    re.IGNORECASE,
)
RE_ASHBY_LINK = re.compile(
    r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)",
    re.IGNORECASE,
)
RE_WORKABLE_LINK = re.compile(
    r"apply\.workable\.com/([a-z0-9_-]+)",
    re.IGNORECASE,
)
RE_SMARTRECRUITERS_LINK = re.compile(
    r"jobs\.smartrecruiters\.com/([a-z0-9_-]+)",
    re.IGNORECASE,
)
RE_JSONLD_JOB = re.compile(r'["\']@type["\']\s*:\s*["\']JobPosting["\']', re.IGNORECASE)
DISCOVERY_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")


def normalize_company_name(name: str) -> str:
    """Normalize company name for matching and deduplication.

    - lowercase
    - strip punctuation
    - drop trailing words (inc, llc, ltd, pvt, corp, etc.)
    - collapse whitespace
    """
    if not name:
        return ""
    # Remove punctuation
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in name.lower())
    words = cleaned.split()

    # Drop trailing corporate suffix words
    while words and words[-1] in TRAILING_WORDS:
        words.pop()

    return " ".join(words).strip()


def company_names_match(input_name: str, board_name: str) -> bool:
    """Compare a seed name with an ATS-provided board name after normalization."""
    input_normalized = normalize_company_name(input_name)
    board_normalized = normalize_company_name(board_name)
    return bool(input_normalized and board_normalized and input_normalized == board_normalized)


def generate_slugs(norm_name: str) -> list[str]:
    """Generate up to 4 candidate slugs for a normalized company name.

    1. no-space name ('acmecorp')
    2. hyphenated ('acme-corp')
    3. no-space + 'hq' ('acmecorphq')
    4. no-space + 'inc' ('acmecorpinc')
    (No first-word-only slugs)
    """
    if not norm_name:
        return []

    words = norm_name.split()
    if not words:
        return []

    no_space = "".join(words)
    hyphenated = "-".join(words)

    candidates = [
        no_space,
        hyphenated,
        f"{no_space}hq",
        f"{no_space}inc",
    ]

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)

    return result[:4]


def extract_domain(website: str | None) -> str | None:
    """Extract clean domain from URL or domain string."""
    if not website or not isinstance(website, str):
        return None
    w = website.strip()
    if not w:
        return None
    if not w.startswith("http://") and not w.startswith("https://"):
        w = f"https://{w}"
    try:
        parsed = urlparse(w)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split(":")[0] if domain else None
    except Exception:
        return None


class RateLimiter:
    """Simple async rate limiter."""

    def __init__(self, rps: float = 2.0):
        self.rps = max(0.1, min(rps, 5.0))  # Hard cap 5
        self.interval = 1.0 / self.rps
        self.last_time = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_time
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self.last_time = time.monotonic()


class DiscoveryManager:
    def __init__(
        self,
        rps: float = 2.0,
        progress_path: str = "data/discover_progress.json",
        candidates_path: str = "config/companies_candidates.csv",
        unsupported_path: str = "config/unsupported_ats_hits.csv",
        custom_pages_path: str = "config/custom_pages.csv",
    ):
        self.rate_limiter = RateLimiter(rps)
        self.progress_path = Path(progress_path)
        self.candidates_path = Path(candidates_path)
        self.unsupported_path = Path(unsupported_path)
        self.custom_pages_path = Path(custom_pages_path)

        self.progress: set[str] = set()
        self.probes_since_save = 0
        self.load_progress()
        self._init_output_files()

    def load_progress(self) -> None:
        if self.progress_path.exists():
            try:
                with open(self.progress_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.progress = set(data) if isinstance(data, list) else set()
                logger.info("Loaded %d already-probed keys from progress file", len(self.progress))
            except Exception as e:
                logger.warning("Could not read progress file %s: %s", self.progress_path, e)

    def save_progress(self) -> None:
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.progress_path, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self.progress)), f, indent=2)
            self.probes_since_save = 0
        except Exception as e:
            logger.warning("Could not save progress file: %s", e)

    def record_probe(self, key: str) -> None:
        self.progress.add(key)
        self.probes_since_save += 1
        if self.probes_since_save >= 50:
            self.save_progress()

    def _init_output_files(self) -> None:
        self.candidates_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.candidates_path.exists():
            with open(self.candidates_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "name", "ats", "slug", "tier", "job_count",
                    "india_job_count", "board_name", "sample_url", "source"
                ])

        if not self.unsupported_path.exists():
            with open(self.unsupported_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "ats", "url"])

        if not self.custom_pages_path.exists():
            with open(self.custom_pages_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "url", "signal"])

    def record_candidate(
        self,
        name: str,
        ats: str,
        slug: str,
        job_count: int,
        india_job_count: int,
        board_name: str,
        sample_url: str,
        source: str = "probe",
    ) -> None:
        tier = 2 if india_job_count > 0 else 3
        with open(self.candidates_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                name, ats, slug, tier, job_count,
                india_job_count, board_name, sample_url, source
            ])

    def record_unsupported(self, name: str, ats: str, url: str) -> None:
        with open(self.unsupported_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([name, ats, url])

    def record_custom_page(self, name: str, url: str, signal: str = "jsonld") -> None:
        with open(self.custom_pages_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([name, url, signal])

    async def probe_ats_slug(
        self,
        session: aiohttp.ClientSession,
        company_name: str,
        ats: str,
        slug: str,
    ) -> dict | None:
        """Probe an ATS slug. Returns dict of board details if valid, else None."""
        key = f"{company_name}|{ats}|{slug}"
        if key in self.progress:
            return None

        await self.rate_limiter.wait()

        dummy_comp = Company(name=company_name, ats=ats, slug=slug, tier=2)
        adapter = ADAPTERS.get(ats)
        if not adapter:
            return None

        try:
            board_name = ""
            if ats == "smartrecruiters":
                jobs, board_name = await adapter.fetch_with_board_name(
                    session,
                    dummy_comp,
                    timeout_seconds=10.0,
                    retries=1,
                )
            else:
                jobs = await adapter.fetch(
                    session,
                    dummy_comp,
                    timeout_seconds=10.0,
                    retries=1,
                )
            # SmartRecruiters answers 200 with an empty list for any slug, so an
            # empty response proves nothing about the company; reject it.
            if ats == "smartrecruiters" and not jobs:
                self.record_probe(key)
                return None

            # Valid board reached
            job_count = len(jobs)
            india_jobs = [j for j in jobs if detect_country(j.location) == "India"]
            india_job_count = len(india_jobs)
            sample_url = jobs[0].url if jobs else ""

            if ats == "greenhouse":
                gh_info_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}"
                try:
                    await self.rate_limiter.wait()
                    async with session.get(gh_info_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if isinstance(data, dict):
                                candidate_name = data.get("name")
                                if isinstance(candidate_name, str):
                                    board_name = candidate_name.strip()
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                    logger.warning(
                        "Could not verify Greenhouse board name for %s: %s",
                        slug,
                        exc,
                    )
            if board_name and not company_names_match(company_name, board_name):
                logger.warning(
                    "Slug collision: input %r resolved to %s board %r (%s); not adding it.",
                    company_name,
                    ats,
                    board_name,
                    slug,
                )
                self.record_probe(key)
                return None

            self.record_probe(key)
            return {
                "name": company_name,
                "ats": ats,
                "slug": slug,
                "job_count": job_count,
                "india_job_count": india_job_count,
                "board_name": board_name,
                "sample_url": sample_url,
            }
        except NotFoundError:
            self.record_probe(key)
            return None
        except Exception as exc:
            logger.warning(
                "Could not probe %s board %s for %s; it will be retried: %s",
                ats,
                slug,
                company_name,
                exc,
            )
            return None

    async def check_careers_page(
        self,
        session: aiohttp.ClientSession,
        company_name: str,
        domain: str,
    ) -> bool:
        """Step 2: Scan careers page on company domain for ATS links."""
        careers_paths = ["/careers", "/jobs", "/about/careers", "/company/careers"]

        # Check robots.txt
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"https://{domain}/robots.txt"
        try:
            rp.set_url(robots_url)
            rp.read()
        except Exception:
            pass

        for path in careers_paths:
            url = f"https://{domain}{path}"
            try:
                if not rp.can_fetch("JobRadar/1.0", url):
                    continue
            except Exception:
                pass

            await asyncio.sleep(1.0)  # Max 1 req/s per host
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as resp:
                    if resp.status != 200:
                        continue
                    html_text = await resp.text()

                    # 1. Scan for supported ATS links
                    m_gh = RE_GH_LINK.search(html_text)
                    if m_gh:
                        slug = m_gh.group(1).lower()
                        probe_res = await self.probe_ats_slug(session, company_name, "greenhouse", slug)
                        if probe_res:
                            probe_res["source"] = "careers_page"
                            self.record_candidate(**probe_res)
                            return True

                    m_lever = RE_LEVER_LINK.search(html_text)
                    if m_lever:
                        slug = m_lever.group(1).lower()
                        probe_res = await self.probe_ats_slug(session, company_name, "lever", slug)
                        if probe_res:
                            probe_res["source"] = "careers_page"
                            self.record_candidate(**probe_res)
                            return True

                    m_ashby = RE_ASHBY_LINK.search(html_text)
                    if m_ashby:
                        slug = m_ashby.group(1).lower()
                        probe_res = await self.probe_ats_slug(session, company_name, "ashby", slug)
                        if probe_res:
                            probe_res["source"] = "careers_page"
                            self.record_candidate(**probe_res)
                            return True

                    m_workable = RE_WORKABLE_LINK.search(html_text)
                    if m_workable:
                        slug = m_workable.group(1).lower()
                        probe_res = await self.probe_ats_slug(session, company_name, "workable", slug)
                        if probe_res:
                            probe_res["source"] = "careers_page"
                            self.record_candidate(**probe_res)
                            return True

                    m_smartrecruiters = RE_SMARTRECRUITERS_LINK.search(html_text)
                    if m_smartrecruiters:
                        slug = m_smartrecruiters.group(1).lower()
                        probe_res = await self.probe_ats_slug(
                            session,
                            company_name,
                            "smartrecruiters",
                            slug,
                        )
                        if probe_res:
                            probe_res["source"] = "careers_page"
                            self.record_candidate(**probe_res)
                            return True

                    # 2. Unsupported ATS hits
                    if "myworkdayjobs.com" in html_text:
                        self.record_unsupported(company_name, "workday", url)
                    elif "zohorecruit" in html_text:
                        self.record_unsupported(company_name, "zohorecruit", url)

                    # 3. JSON-LD JobPosting detection
                    if RE_JSONLD_JOB.search(html_text):
                        self.record_custom_page(company_name, url, "jsonld")

                    return False
            except Exception:
                continue

        return False


def load_input_companies(input_paths: list[str] | None = None) -> list[dict]:
    """Load and normalize companies from input files."""
    files_to_read: list[Path] = []

    if input_paths:
        for p_str in input_paths:
            p = Path(p_str)
            if p.exists():
                files_to_read.append(p)
    else:
        # Defaults: every tracked seed list and config/inputs/.
        files_to_read.extend(sorted(Path("config").glob("seed_company_names*.txt")))

        inputs_dir = Path("config/inputs")
        if inputs_dir.exists():
            for p in inputs_dir.glob("*"):
                if p.is_file() and p.suffix.lower() in (".txt", ".csv"):
                    files_to_read.append(p)

    raw_items: list[dict] = []
    for fp in files_to_read:
        if fp.suffix.lower() == ".txt":
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    raw_items.append({"name": line, "website": None})
        elif fp.suffix.lower() == ".csv":
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    # Case-insensitive column resolution
                    fields = {col.strip().lower(): col for col in reader.fieldnames if col}
                    name_col = fields.get("name")
                    site_col = fields.get("website")
                    if name_col:
                        for row in reader:
                            name_val = (row.get(name_col) or "").strip()
                            if name_val and not name_val.startswith("#"):
                                site_val = (row.get(site_col) or "").strip() if site_col else None
                                raw_items.append({"name": name_val, "website": site_val or None})

    # Deduplicate across all inputs by normalized name and domain
    seen_names: set[str] = set()
    seen_domains: set[str] = set()
    deduped: list[dict] = []

    for item in raw_items:
        raw_name = item["name"]
        norm_name = normalize_company_name(raw_name)
        if not norm_name or norm_name in seen_names:
            continue

        domain = extract_domain(item.get("website"))
        if domain and domain in seen_domains:
            continue

        seen_names.add(norm_name)
        if domain:
            seen_domains.add(domain)

        deduped.append({
            "name": raw_name,
            "norm_name": norm_name,
            "website": item.get("website"),
            "domain": domain,
        })

    return deduped


def merge_candidates(
    candidates_path: str = "config/companies_candidates.csv",
    companies_path: str = "config/companies.csv",
) -> int:
    """Merge candidates into companies.csv safely.

    - Appends candidate rows using only name,ats,slug,tier.
    - Skips any (ats, slug) already present.
    - Writes backup companies.csv.bak before modifying.
    - Running twice adds 0 rows.
    """
    cand_p = Path(candidates_path)
    comp_p = Path(companies_path)

    if not cand_p.exists():
        print(f"Candidates file not found: {cand_p}")
        return 0

    if not comp_p.exists():
        print(f"Companies file not found: {comp_p}")
        return 0

    # Read existing companies
    existing_keys: set[str] = set()
    with open(comp_p, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#") or len(row) < 4:
                continue
            ats = row[1].strip().lower()
            slug = row[2].strip()
            existing_keys.add(f"{ats}:{slug}")

    # Read candidates
    new_rows: list[list[str]] = []
    with open(cand_p, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            ats = (row.get("ats") or "").strip().lower()
            slug = (row.get("slug") or "").strip()
            tier = (row.get("tier") or "3").strip()
            if not name or not ats or not slug:
                continue
            key = f"{ats}:{slug}"
            if key not in existing_keys:
                existing_keys.add(key)
                new_rows.append([name, ats, slug, tier])

    if not new_rows:
        print("Merge: 0 new companies to add (all already present).")
        return 0

    # Write backup
    backup_p = comp_p.with_suffix(".csv.bak")
    shutil.copyfile(comp_p, backup_p)
    logger.info("Created backup at %s", backup_p)

    # Append new rows
    with open(comp_p, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in new_rows:
            writer.writerow(row)

    print(f"Merge: Added {len(new_rows)} new company row(s) to {comp_p} (backup at {backup_p})")
    return len(new_rows)


async def run_discovery(args) -> int:
    """Execute the discovery pipeline."""
    if getattr(args, "merge", False):
        merge_candidates()
        return 0

    companies = load_input_companies(getattr(args, "input", None))
    print(f"Loaded {len(companies)} unique companies for discovery probing.")

    manager = DiscoveryManager(rps=getattr(args, "rps", 2.0))
    headers = {"User-Agent": "JobRadar/1.0 (personal job search)"}

    found_count = 0
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            for idx, c in enumerate(companies, start=1):
                name = c["name"]
                norm_name = c["norm_name"]
                domain = c.get("domain")

                if idx % 25 == 0 or idx == 1:
                    print(f"[{idx}/{len(companies)}] Probing progress... (found {found_count} candidate boards so far)", flush=True)

                slug_candidates = generate_slugs(norm_name)
                found_for_company = False
                found_ats: list[str] = []

                for ats in DISCOVERY_ATS:
                    for slug in slug_candidates:
                        probe_res = await manager.probe_ats_slug(session, name, ats, slug)
                        if probe_res:
                            found_for_company = True
                            found_ats.append(ats)
                            found_count += 1
                            manager.record_candidate(**probe_res, source="probe")
                            print(
                                f"[{idx}/{len(companies)}] FOUND: {name} -> {ats}:{slug} "
                                f"(jobs: {probe_res['job_count']}, India: {probe_res['india_job_count']})",
                                flush=True,
                            )
                            # Stop probing this ATS at first hit
                            break

                if len(found_ats) > 1:
                    logger.info(
                        "multi_ats: %s found on %s",
                        name,
                        ", ".join(found_ats),
                    )

                # Step 2: if no board found and domain present, scan careers page
                if not found_for_company and domain:
                    hit = await manager.check_careers_page(session, name, domain)
                    if hit:
                        found_count += 1
                        print(f"[{idx}/{len(companies)}] FOUND via careers page: {name} ({domain})", flush=True)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nInterrupted by user. Saving discovery progress...")
    finally:
        manager.save_progress()

    print(
        f"Discovery completed. screened={len(manager.progress)} "
        f"found={found_count} kept={found_count}."
    )
    return 0
