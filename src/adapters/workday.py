"""Workday ATS adapter with per-tenant CXS API parsing."""
import logging
from typing import Any
from urllib.parse import urlparse
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job

logger = logging.getLogger(__name__)


class WorkdayAdapter:
    ats: str = "workday"

    def _resolve_endpoints(self, company: Company) -> tuple[str, str, str]:
        """Resolve (api_url, base_web_url, site) from company slug and extra field.

        Supported extra formats:
        1. Full jobs URL: https://{tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
        2. Config string: 'tenant={t};site={s};wd={wdN}' or '{site}|{wdN}' or '{site}/{wdN}'
        """
        extra = (company.extra or "").strip()
        if extra.startswith("http://") or extra.startswith("https://"):
            api_url = extra
            parsed = urlparse(extra)
            base_web_url = f"{parsed.scheme}://{parsed.netloc}"
            # Extract site from /wday/cxs/{tenant}/{site}/jobs
            parts = parsed.path.strip("/").split("/")
            site = parts[3] if len(parts) >= 4 else company.slug
            return api_url, base_web_url, site

        tenant = company.slug
        site = company.slug
        wd = "wd1"

        if extra:
            if ";" in extra:
                params = dict(part.split("=", 1) for part in extra.split(";") if "=" in part)
                tenant = params.get("tenant", tenant).strip()
                site = params.get("site", site).strip()
                wd = params.get("wd", wd).strip()
            elif "|" in extra:
                p = extra.split("|")
                site = p[0].strip()
                if len(p) > 1:
                    wd = p[1].strip()
            elif "/" in extra:
                p = extra.split("/")
                site = p[0].strip()
                if len(p) > 1:
                    wd = p[1].strip()

        api_url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        base_web_url = f"https://{tenant}.{wd}.myworkdayjobs.com"
        return api_url, base_web_url, site

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        api_url, _, _ = self._resolve_endpoints(company)
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
        raw = await get_json(
            session,
            api_url,
            method="POST",
            json_body=payload,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw Workday CXS data to Job dataclasses."""
        if not isinstance(raw, dict):
            logger.warning("Workday response for %s is not a dict: %s", company.key, type(raw))
            return []

        postings = raw.get("jobPostings")
        if not isinstance(postings, list):
            logger.warning("Workday response for %s missing 'jobPostings' list", company.key)
            return []

        _, base_web_url, site = self._resolve_endpoints(company)
        jobs: list[Job] = []

        for item in postings:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            external_path = item.get("externalPath")

            if not title or not external_path or not isinstance(title, str) or not title.strip():
                continue

            title = title.strip()
            path_clean = external_path.strip()

            # Extract native_id from path e.g. /job/Location/Title_JR1234 -> JR1234
            if "_" in path_clean:
                native_id = path_clean.rsplit("_", 1)[-1]
            else:
                native_id = path_clean.strip("/").replace("/", "_")

            url = f"{base_web_url}/{site}{path_clean}"
            location = (item.get("locationsText") or "").strip()

            jobs.append(
                Job(
                    job_id=f"{self.ats}:{company.slug}:{native_id}",
                    company_key=company.key,
                    company=company.name,
                    ats=self.ats,
                    title=title,
                    location=location,
                    url=url,
                    description="",
                    posted_at=None,
                    salary=None,
                    remote=None,
                )
            )

        return jobs
