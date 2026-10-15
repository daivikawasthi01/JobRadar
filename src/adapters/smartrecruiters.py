"""SmartRecruiters ATS adapter."""
import logging
from typing import Any
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job
from src.textutil import normalize_iso

logger = logging.getLogger(__name__)


class SmartRecruitersAdapter:
    ats: str = "smartrecruiters"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        jobs, _ = await self.fetch_with_board_name(
            session,
            company,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return jobs

    async def fetch_with_board_name(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> tuple[list[Job], str]:
        url = f"https://api.smartrecruiters.com/v1/companies/{company.slug}/postings"
        raw = await get_json(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company), self.extract_board_name(raw)

    @staticmethod
    def extract_board_name(raw: Any) -> str:
        """Return a single ATS-provided company name when postings agree."""
        if not isinstance(raw, dict) or not isinstance(raw.get("content"), list):
            return ""
        names: dict[str, str] = {}
        for item in raw["content"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("company"), dict)
                or not isinstance(item["company"].get("name"), str)
            ):
                continue
            name = item["company"]["name"].strip()
            if name:
                names.setdefault(name.casefold(), name)
        return next(iter(names.values())) if len(names) == 1 else ""

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw SmartRecruiters data to Job dataclasses."""
        if not isinstance(raw, dict):
            logger.warning("SmartRecruiters response for %s is not a dict: %s", company.key, type(raw))
            return []

        postings = raw.get("content")
        if not isinstance(postings, list):
            logger.warning("SmartRecruiters response for %s missing 'content' list", company.key)
            return []

        jobs: list[Job] = []
        for item in postings:
            if not isinstance(item, dict):
                continue

            native_id = item.get("id")
            title = item.get("name")

            if native_id is None or not title or not isinstance(title, str) or not title.strip():
                continue

            title = title.strip()
            native_id_str = str(native_id).strip()
            url = f"https://jobs.smartrecruiters.com/{company.slug}/{native_id_str}"

            # Location and remote
            location = ""
            remote = None
            loc_data = item.get("location")
            if isinstance(loc_data, dict):
                full_loc = loc_data.get("fullLocation")
                city = loc_data.get("city")
                country = loc_data.get("country")
                if full_loc:
                    location = full_loc.strip()
                elif city and country:
                    location = f"{city}, {country}".strip()
                elif city:
                    location = city.strip()
                remote_val = loc_data.get("remote")
                if isinstance(remote_val, bool):
                    remote = remote_val
            elif isinstance(loc_data, str):
                location = loc_data.strip()

            posted_at = normalize_iso(item.get("releasedDate"))

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
