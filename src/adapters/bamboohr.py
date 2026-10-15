"""Adapter for public BambooHR careers listings."""
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from src.fetcher import get_json
from src.models import Company, Job
logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"^[a-z0-9-]+$", re.IGNORECASE)


class BambooHRAdapter:
    ats: str = "bamboohr"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        if not _SLUG_RE.fullmatch(company.slug):
            raise ValueError(f"Invalid BambooHR board slug for {company.key}")

        url = f"https://{company.slug}.bamboohr.com/careers/list"
        raw = await get_json(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Parse the observed public BambooHR careers-list JSON response."""
        if not isinstance(raw, dict):
            logger.warning("BambooHR response for %s is not a dict", company.key)
            return []

        results = raw.get("result")
        if not isinstance(results, list):
            logger.warning("BambooHR response for %s missing 'result' list", company.key)
            return []

        jobs: list[Job] = []
        seen_ids: set[str] = set()
        board_host = f"{company.slug}.bamboohr.com"

        for item in results:
            if not isinstance(item, dict):
                continue

            native_id = item.get("id")
            title = item.get("jobOpeningName")
            if native_id is None or not isinstance(title, str) or not title.strip():
                continue
            native_id = str(native_id).strip()
            if not native_id or native_id in seen_ids:
                continue
            seen_ids.add(native_id)

            location_data = item.get("location")
            if not isinstance(location_data, dict):
                location_data = {}
            ats_location = item.get("atsLocation")
            if not isinstance(ats_location, dict):
                ats_location = {}
            parts = []
            for key in ("city", "state", "province", "country"):
                value = location_data.get(key) or ats_location.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    if text.casefold() not in {part.casefold() for part in parts}:
                        parts.append(text)
            location = ", ".join(parts)

            remote = item.get("isRemote")
            if not isinstance(remote, bool):
                remote = None

            description = item.get("description")
            jobs.append(
                Job(
                    job_id=f"{self.ats}:{company.slug}:{native_id}",
                    company_key=company.key,
                    company=company.name,
                    ats=self.ats,
                    title=title.strip(),
                    location=location,
                    url=f"https://{board_host}/careers/{quote(native_id, safe='')}",
                    description="",
                    posted_at=None,
                    salary=None,
                    remote=remote,
                )
            )

        return jobs
