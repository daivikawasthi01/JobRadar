"""Ashby ATS adapter."""
import logging
from typing import Any
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job
from src.textutil import html_to_text, normalize_iso

logger = logging.getLogger(__name__)


class AshbyAdapter:
    ats: str = "ashby"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company.slug}?includeCompensation=true"
        raw = await get_json(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw Ashby job board data into Job dataclasses."""
        if not isinstance(raw, dict):
            logger.warning("Ashby response for %s is not a dict: %s", company.key, type(raw))
            return []

        jobs_data = raw.get("jobs")
        if not isinstance(jobs_data, list):
            logger.warning("Ashby response for %s missing 'jobs' list", company.key)
            return []

        jobs: list[Job] = []
        for item in jobs_data:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict job item in Ashby for %s", company.key)
                continue

            # Skip unlisted entries per spec
            if item.get("isListed") is False:
                continue

            native_id = item.get("id")
            title = item.get("title")
            url = item.get("jobUrl")

            # Empty/missing title or URL -> skip entry
            if native_id is None or not title or not isinstance(title, str) or not title.strip():
                logger.warning("Skipping Ashby job with missing id/title: %s", item)
                continue
            if not url or not isinstance(url, str) or not url.strip():
                logger.warning("Skipping Ashby job with missing url: %s", item)
                continue

            title = title.strip()
            url = url.strip()
            native_id_str = str(native_id).strip()

            # Location: location -> location
            location = ""
            loc_val = item.get("location")
            if isinstance(loc_val, str):
                location = loc_val.strip()

            # Description: descriptionPlain (fallback descriptionHtml via html_to_text)
            desc_plain = item.get("descriptionPlain")
            if desc_plain and isinstance(desc_plain, str) and desc_plain.strip():
                description = desc_plain.strip()
            else:
                desc_html = item.get("descriptionHtml") or ""
                description = html_to_text(str(desc_html))

            # Posted at: publishedAt
            published_at = item.get("publishedAt")
            posted_at = normalize_iso(published_at) if published_at else None

            # Remote: isRemote
            remote: bool | None = None
            is_remote_val = item.get("isRemote")
            if isinstance(is_remote_val, bool):
                remote = is_remote_val

            # Compensation summary if present
            salary: str | None = None
            comp_val = item.get("compensation")
            if isinstance(comp_val, dict):
                summary = (
                    comp_val.get("compensationTierSummary")
                    or comp_val.get("scrapeableCompensationSalarySummary")
                )
                if summary and isinstance(summary, str) and summary.strip():
                    salary = summary.strip()
            elif isinstance(comp_val, str) and comp_val.strip():
                salary = comp_val.strip()

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
                    salary=salary,
                    remote=remote,
                )
            )

        return jobs
