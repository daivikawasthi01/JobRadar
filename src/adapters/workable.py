"""Workable ATS adapter."""
import logging
from typing import Any
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job
from src.textutil import normalize_iso

logger = logging.getLogger(__name__)


class WorkableAdapter:
    ats: str = "workable"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        url = f"https://apply.workable.com/api/v3/accounts/{company.slug}/jobs"
        raw = await get_json(
            session,
            url,
            method="POST",
            json_body={},
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw Workable data to Job dataclasses."""
        if not isinstance(raw, dict):
            logger.warning("Workable response for %s is not a dict: %s", company.key, type(raw))
            return []

        results = raw.get("results")
        if not isinstance(results, list):
            logger.warning("Workable response for %s missing 'results' list", company.key)
            return []

        jobs: list[Job] = []
        for item in results:
            if not isinstance(item, dict):
                continue

            native_id = item.get("shortcode") or item.get("id")
            title = item.get("title")

            if not native_id or not title or not isinstance(title, str) or not title.strip():
                continue

            title = title.strip()
            native_id_str = str(native_id).strip()
            url = f"https://apply.workable.com/{company.slug}/j/{native_id_str}/"

            # Location and remote
            location = ""
            loc_data = item.get("location")
            if isinstance(loc_data, dict):
                city = loc_data.get("city") or ""
                country = loc_data.get("country") or ""
                parts = [p for p in [city, country] if p]
                location = ", ".join(parts)
            elif isinstance(loc_data, str):
                location = loc_data.strip()

            remote: bool | None = None
            if isinstance(item.get("remote"), bool):
                remote = item["remote"]
            elif item.get("workplace"):
                remote = (str(item["workplace"]).lower() == "remote")

            posted_at = normalize_iso(item.get("published"))

            jobs.append(
                Job(
                    job_id=f"{self.ats}:{company.slug}:{native_id_str}",
                    company_key=company.key,
                    company=company.name,
                    ats=self.ats,
                    title=title,
                    location=location,
                    url=url,
                    description="",
                    posted_at=posted_at,
                    salary=None,
                    remote=remote,
                )
            )

        return jobs
