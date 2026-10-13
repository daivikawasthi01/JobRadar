"""Greenhouse ATS adapter."""
import logging
from typing import Any
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job
from src.textutil import html_to_text, normalize_iso

logger = logging.getLogger(__name__)


class GreenhouseAdapter:
    ats: str = "greenhouse"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company.slug}/jobs?content=true"
        raw = await get_json(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw Greenhouse data into Job dataclasses."""
        if not isinstance(raw, dict):
            logger.warning("Greenhouse response for %s is not a dict: %s", company.key, type(raw))
            return []

        jobs_data = raw.get("jobs")
        if not isinstance(jobs_data, list):
            logger.warning("Greenhouse response for %s missing 'jobs' list", company.key)
            return []

        jobs: list[Job] = []
        for item in jobs_data:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict job item in Greenhouse for %s", company.key)
                continue

            native_id = item.get("id")
            title = item.get("title")
            url = item.get("absolute_url")

            # Empty/missing title or URL -> skip entry
            if native_id is None or not title or not isinstance(title, str) or not title.strip():
                logger.warning("Skipping Greenhouse job with missing id/title: %s", item)
                continue
            if not url or not isinstance(url, str) or not url.strip():
                logger.warning("Skipping Greenhouse job with missing url: %s", item)
                continue

            title = title.strip()
            url = url.strip()
            native_id_str = str(native_id).strip()

            # Location: location.name -> location
            location = ""
            loc_val = item.get("location")
            if isinstance(loc_val, dict):
                location = (loc_val.get("name") or "").strip()
            elif isinstance(loc_val, str):
                location = loc_val.strip()

            # Description: content (HTML-escaped) -> plain text via html_to_text
            content_val = item.get("content") or ""
            description = html_to_text(str(content_val))

            # Posted at: first_published if present else updated_at
            first_published = item.get("first_published")
            updated_at = item.get("updated_at")
            posted_at_raw = first_published if first_published else updated_at
            posted_at = normalize_iso(posted_at_raw) if posted_at_raw else None

            jobs.append(
                Job(
                    job_id=f"{self.ats}:{company.slug}:{native_id_str}",
                    company_key=company.key,
                    company=company.name,
                    ats=self.ats,
                    title=title,
                    location=location,
                    url=url,
                    description=description,
                    posted_at=posted_at,
                    salary=None,
                    remote=None,
                )
            )

        return jobs
