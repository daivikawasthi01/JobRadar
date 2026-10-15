#!/usr/bin/env python3
"""Harvest ATS board slugs from Common Crawl and propose relevant boards."""
import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.adapters import ADAPTERS
from src.filters import detect_country
from src.models import Company

logger = logging.getLogger("jobradar.harvest")

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
USER_AGENT = "JobRadar-CommonCrawl-harvester/1.0 (weekly company discovery)"
ATS_HOSTS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
    "ashby": ("jobs.ashbyhq.com",),
    "workable": ("apply.workable.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com",),
}
PREFIX_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
INTERN_TITLE = re.compile(r"\bintern(?:s|ship|ships)?\b", re.IGNORECASE)
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class HarvestError(Exception):
    """Raised for invalid Common Crawl data or invalid local harvest state."""


class RateLimiter:
    """Enforce a minimum delay between requests."""

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.interval = 1.0 / requests_per_second
        self.last_request = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_request = time.monotonic()


def parse_board_slug(url: str, ats: str) -> str | None:
    """Extract a board slug only from a job-detail URL on the expected ATS host."""
    if ats not in ATS_HOSTS:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in ATS_HOSTS[ats]:
        return None
    parts = [part for part in parsed.path.split("/") if part]

    if ats == "greenhouse":
        if len(parts) < 3 or parts[1].lower() not in {"jobs", "job"}:
            return None
        slug = parts[0]
    elif ats == "workable":
        if len(parts) < 3 or parts[1].lower() != "j":
            return None
        slug = parts[0]
    else:
        if len(parts) < 2:
            return None
        slug = parts[0]

    slug = slug.lower()
    if not SLUG.fullmatch(slug):
        return None
    return slug


def parse_index_metadata(body: str) -> int:
    """Return the Common Crawl CDX page count from its metadata response."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HarvestError(f"Invalid Common Crawl page metadata: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pages"), int):
        raise HarvestError("Common Crawl metadata is missing its integer 'pages' field.")
    pages = data["pages"]
    if pages < 0:
        raise HarvestError(f"Common Crawl returned an invalid page count: {pages}")
    return pages


def parse_index_records(body: str) -> list[str]:
    """Parse newline-delimited Common Crawl index JSON rows."""
    urls: list[str] = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarvestError(f"Invalid Common Crawl row {line_number}: {exc}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            raise HarvestError(f"Common Crawl row {line_number} is missing a URL.")
        urls.append(row["url"])
    return urls


def _display_name(slug: str) -> str:
    return re.sub(r"\s+", " ", slug.replace("-", " ").replace("_", " ")).strip().title()


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "completed_prefixes": [],
            "split_prefixes": [],
            "pending": {},
            "screened": {},
            "unresolved_prefixes": {},
        }
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarvestError(f"Could not read harvest cache {path}: {exc}") from exc
    if not isinstance(cache, dict) or cache.get("version") != 1:
        raise HarvestError(f"Unsupported or invalid harvest cache format in {path}.")
    for key in (
        "completed_prefixes",
        "split_prefixes",
        "pending",
        "screened",
        "unresolved_prefixes",
    ):
        if key not in cache:
            cache[key] = {} if key in {"pending", "screened", "unresolved_prefixes"} else []
    return cache


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            json.dump(cache, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    except OSError as exc:
        raise HarvestError(f"Could not save harvest cache {path}: {exc}") from exc


def _query_index(
    api_url: str,
    parameters: dict[str, str | int],
    limiter: RateLimiter,
    timeout: float,
    retries: int,
) -> str:
    query = urlencode(parameters)
    request = Request(
        f"{api_url}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(retries + 1):
        limiter.wait()
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code <= 599:
                if attempt < retries:
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 60.0) if retry_after else 2 ** attempt
                    except ValueError:
                        delay = 2 ** attempt
                    logger.warning(
                        "Common Crawl returned HTTP %d; retrying after %.1fs",
                        exc.code,
                        delay,
                    )
                    time.sleep(delay)
                    continue
            raise HarvestError(f"Common Crawl request failed with HTTP {exc.code}: {exc}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            if attempt < retries:
                delay = 2 ** attempt
                logger.warning("Common Crawl request failed; retrying after %ds: %s", delay, exc)
                time.sleep(delay)
                continue
            raise HarvestError(f"Common Crawl request failed after {retries + 1} attempts: {exc}") from exc
    raise HarvestError("Common Crawl request retries exhausted.")


class CommonCrawlHarvester:
    def __init__(
        self,
        cache_path: Path,
        rps: float = 1.0,
        timeout: float = 60.0,
        retries: int = 2,
        max_prefix_depth: int = 2,
        request: Any = _query_index,
    ) -> None:
        if not 1 <= max_prefix_depth <= 4:
            raise ValueError("max_prefix_depth must be between 1 and 4")
        self.cache_path = cache_path
        self.cache = load_cache(cache_path)
        self.limiter = RateLimiter(rps)
        self.timeout = timeout
        self.retries = retries
        self.max_prefix_depth = max_prefix_depth
        self.request = request
        self.new_slugs = 0

    def _cached_key(self, crawl_id: str, ats: str, host: str, prefix: str) -> str:
        return f"{crawl_id}|{ats}|{host}|{prefix}"

    def _queue_urls(
        self,
        crawl_id: str,
        ats: str,
        host: str,
        urls: list[str],
    ) -> None:
        pending: dict[str, dict[str, Any]] = self.cache["pending"]
        screened: dict[str, dict[str, Any]] = self.cache["screened"]
        for url in urls:
            slug = parse_board_slug(url, ats)
            if not slug:
                continue
            key = f"{ats}:{slug}"
            if key in pending or key in screened:
                continue
            pending[key] = {
                "ats": ats,
                "slug": slug,
                "crawl_ids": [crawl_id],
                "sample_url": url,
            }
            self.new_slugs += 1
        save_cache(self.cache_path, self.cache)

    def harvest_prefix(
        self,
        crawl_id: str,
        api_url: str,
        ats: str,
        host: str,
        prefix: str,
    ) -> None:
        key = self._cached_key(crawl_id, ats, host, prefix)
        if key in self.cache["completed_prefixes"]:
            return
        if key in self.cache["split_prefixes"]:
            for character in PREFIX_CHARS:
                self.harvest_prefix(
                    crawl_id,
                    api_url,
                    ats,
                    host,
                    prefix + character,
                )
            return

        pattern = f"{host}/{prefix}*"
        try:
            metadata = self.request(
                api_url,
                {
                    "url": pattern,
                    "output": "json",
                    "fl": "url",
                    "showNumPages": "true",
                },
                self.limiter,
                self.timeout,
                self.retries,
            )
            page_count = parse_index_metadata(metadata)
            urls: list[str] = []
            for page in range(page_count):
                body = self.request(
                    api_url,
                    {
                        "url": pattern,
                        "output": "json",
                        "fl": "url",
                        "page": page,
                    },
                    self.limiter,
                    self.timeout,
                    self.retries,
                )
                urls.extend(parse_index_records(body))
        except HarvestError as exc:
            self.cache["unresolved_prefixes"][key] = str(exc)
            if len(prefix) >= self.max_prefix_depth:
                logger.warning("Could not query Common Crawl prefix %s: %s", pattern, exc)
                save_cache(self.cache_path, self.cache)
                return
            self.cache["split_prefixes"].append(key)
            self.cache["unresolved_prefixes"].pop(key, None)
            save_cache(self.cache_path, self.cache)
            logger.info("Splitting failed Common Crawl prefix %s", pattern)
            for character in PREFIX_CHARS:
                self.harvest_prefix(
                    crawl_id,
                    api_url,
                    ats,
                    host,
                    prefix + character,
                )
            return

        self._queue_urls(crawl_id, ats, host, urls)
        self.cache["completed_prefixes"].append(key)
        self.cache["unresolved_prefixes"].pop(key, None)
        save_cache(self.cache_path, self.cache)

    def unresolved_count(self) -> int:
        return len(self.cache["unresolved_prefixes"])


def fetch_collections(
    limiter: RateLimiter,
    timeout: float,
    retries: int,
) -> list[dict[str, Any]]:
    body = _query_index(
        COLLECTIONS_URL,
        {},
        limiter,
        timeout,
        retries,
    )
    try:
        collections = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HarvestError(f"Invalid Common Crawl collections response: {exc}") from exc
    if not isinstance(collections, list):
        raise HarvestError("Common Crawl collections response is not a list.")
    valid = [
        collection
        for collection in collections
        if isinstance(collection, dict)
        and isinstance(collection.get("id"), str)
        and isinstance(collection.get("cdx-api"), str)
    ]
    if not valid:
        raise HarvestError("Common Crawl returned no usable collections.")
    return valid


def _company_rows(path: Path) -> tuple[set[str], list[list[str]]]:
    import csv

    if not path.exists():
        raise HarvestError(f"Companies config not found: {path}")
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        rows = [
            row
            for row in reader
            if row and not row[0].strip().startswith("#")
        ]
    if not rows or [cell.strip().lower() for cell in rows[0][:4]] != [
        "name",
        "ats",
        "slug",
        "tier",
    ]:
        raise HarvestError(f"Invalid companies CSV header in {path}.")
    keys = {
        f"{row[1].strip().lower()}:{row[2].strip().lower()}"
        for row in rows[1:]
        if len(row) >= 4 and row[1].strip() and row[2].strip()
    }
    return keys, rows


def _append_company(path: Path, rows: list[list[str]], name: str, ats: str, slug: str, tier: int) -> None:
    import csv

    with path.open("a", encoding="utf-8", newline="") as target:
        csv.writer(target).writerow([name, ats, slug, tier])
    rows.append([name, ats, slug, str(tier)])


async def screen_pending(
    harvester: CommonCrawlHarvester,
    companies_path: Path,
    max_screened: int,
    rps: float,
) -> tuple[int, int, int]:
    existing_keys, company_rows = _company_rows(companies_path)
    pending: dict[str, dict[str, Any]] = harvester.cache["pending"]
    screened: dict[str, dict[str, Any]] = harvester.cache["screened"]
    active_count = rejected_count = transient_errors = attempts = 0
    adapter_errors: dict[str, str] = {}
    limiter = RateLimiter(rps)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": "JobRadar/1.0 (weekly Common Crawl board screening)"},
    ) as session:
        for key in sorted(list(pending)):
            if attempts >= max_screened:
                break
            info = pending[key]
            ats, slug = info["ats"], info["slug"]
            if key in existing_keys:
                screened[key] = {"status": "already_active"}
                pending.pop(key, None)
                save_cache(harvester.cache_path, harvester.cache)
                continue

            limiter.wait()
            attempts += 1
            company = Company(name=_display_name(slug), ats=ats, slug=slug, tier=3)
            try:
                jobs = await ADAPTERS[ats].fetch(
                    session,
                    company,
                    timeout_seconds=30,
                    retries=1,
                )
            except Exception as exc:
                transient_errors += 1
                adapter_errors[key] = str(exc)[:300]
                logger.warning("Temporary screening failure for %s: %s", key, exc)
                continue

            india_job_count = sum(detect_country(job.location) == "India" for job in jobs)
            intern_titles = sum(bool(INTERN_TITLE.search(job.title or "")) for job in jobs)
            passed = bool(india_job_count or intern_titles)
            decision = {
                "status": "accepted" if passed else "rejected",
                "job_count": len(jobs),
                "india_job_count": india_job_count,
                "intern_title_count": intern_titles,
                "screened_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            }
            if passed:
                tier = 2 if india_job_count else 3
                _append_company(
                    companies_path,
                    company_rows,
                    company.name,
                    ats,
                    slug,
                    tier,
                )
                existing_keys.add(key)
                decision["tier"] = tier
                active_count += 1
            else:
                rejected_count += 1
            screened[key] = decision
            pending.pop(key, None)
            save_cache(harvester.cache_path, harvester.cache)

    harvester.cache["screen_errors"] = adapter_errors
    save_cache(harvester.cache_path, harvester.cache)
    return active_count, rejected_count, transient_errors


def _selected_collections(
    collections: list[dict[str, Any]],
    crawl_count: int,
    crawl_ids: list[str] | None,
) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in collections}
    if crawl_ids:
        missing = [crawl_id for crawl_id in crawl_ids if crawl_id not in by_id]
        if missing:
            raise HarvestError(
                f"Requested Common Crawl ID(s) are unavailable: {', '.join(missing)}"
            )
        return [by_id[crawl_id] for crawl_id in crawl_ids]
    return collections[:crawl_count]


def run_harvest(args: argparse.Namespace) -> int:
    cache_path = Path(args.cache)
    companies_path = Path(args.companies)
    request_limiter = RateLimiter(args.rps)
    collections = _selected_collections(
        fetch_collections(request_limiter, args.timeout, args.retries),
        args.crawl_count,
        args.crawl_ids,
    )
    harvester = CommonCrawlHarvester(
        cache_path,
        rps=args.rps,
        timeout=args.timeout,
        retries=args.retries,
        max_prefix_depth=args.max_prefix_depth,
    )
    ats_list = args.ats or list(ATS_HOSTS)
    prefixes = args.prefixes or list(PREFIX_CHARS)

    for collection in collections:
        crawl_id = collection["id"]
        api_url = collection["cdx-api"]
        logger.info("Harvesting Common Crawl collection %s", crawl_id)
        for ats in ats_list:
            for host in ATS_HOSTS[ats]:
                for prefix in prefixes:
                    harvester.harvest_prefix(
                        crawl_id,
                        api_url,
                        ats,
                        host,
                        prefix,
                    )

    active_count, rejected_count, transient_errors = asyncio.run(
        screen_pending(
            harvester,
            companies_path,
            max_screened=args.max_screened,
            rps=args.screen_rps,
        )
    )
    logger.info(
        "Harvest complete: new_slugs=%d accepted=%d rejected=%d pending=%d unresolved_prefixes=%d transient_screen_errors=%d",
        harvester.new_slugs,
        active_count,
        rejected_count,
        len(harvester.cache["pending"]),
        harvester.unresolved_count(),
        transient_errors,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crawl-count", type=int, default=3)
    parser.add_argument("--crawl-ids", nargs="+")
    parser.add_argument("--ats", nargs="+", choices=sorted(ATS_HOSTS))
    parser.add_argument("--prefixes", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--max-prefix-depth", type=int, default=2)
    parser.add_argument("--max-screened", type=int, default=3000)
    parser.add_argument("--rps", type=float, default=1.0)
    parser.add_argument("--screen-rps", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--companies", default="config/companies.csv")
    parser.add_argument("--cache", default="config/commoncrawl_harvest.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    args = build_parser().parse_args(argv)
    if args.crawl_count < 1 or args.max_screened < 1 or args.retries < 0:
        raise SystemExit("--crawl-count, --max-screened must be positive and --retries non-negative")
    if args.rps > 1 or args.screen_rps > 1:
        raise SystemExit("Common Crawl index and ATS screening rates are capped at 1 request per second.")
    try:
        return run_harvest(args)
    except HarvestError as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
