"""Lever ATS adapter."""
import logging
from typing import Any
import aiohttp
from src.fetcher import get_json
from src.models import Company, Job
from src.textutil import epoch_ms_to_iso, html_to_text

logger = logging.getLogger(__name__)


class LeverAdapter:
    ats: str = "lever"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        url = f"https://api.lever.co/v0/postings/{company.slug}?mode=json"
        raw = await get_json(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw Lever postings into Job dataclasses."""
        if not isinstance(raw, list):
            logger.warning("Lever response for %s is not a list: %s", company.key, type(raw))
            return []

        jobs: list[Job] = []
        for item in raw:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict job item in Lever for %s", company.key)
                continue

            native_id = item.get("id")
            title = item.get("text")
            url = item.get("hostedUrl")

            # Empty/missing title or URL -> skip entry
            if native_id is None or not title or not isinstance(title, str) or not title.strip():
                logger.warning("Skipping Lever job with missing id/title: %s", item)
                continue
            if not url or not isinstance(url, str) or not url.strip():
                logger.warning("Skipping Lever job with missing url: %s", item)
                continue

            title = title.strip()
            url = url.strip()
            native_id_str = str(native_id).strip()

            # Location: categories.location -> location
            location = ""
            cats = item.get("categories")
            if isinstance(cats, dict):
                location = (cats.get("location") or "").strip()
            elif isinstance(cats, str):
                location = cats.strip()

            # Description: descriptionPlain (fallback description via html_to_text; also append lists[])
            desc_plain = item.get("descriptionPlain")
            if desc_plain and isinstance(desc_plain, str) and desc_plain.strip():
                description = desc_plain.strip()
            else:
                desc_html = item.get("description") or ""
                description = html_to_text(str(desc_html))

            # Append text of lists[] if present
            lists_val = item.get("lists")
            if isinstance(lists_val, list):
                list_parts: list[str] = []
                for lst in lists_val:
                    if isinstance(lst, dict):
                        header = (lst.get("text") or "").strip()
                        content = html_to_text(lst.get("content"))
                        if header and content:
                            list_parts.append(f"{header}: {content}")
                        elif content:
                            list_parts.append(content)
                        elif header:
                            list_parts.append(header)
                if list_parts:
                    extra_text = " ".join(list_parts)
                    description = f"{description} {extra_text}".strip()

            # Posted at: createdAt (epoch ms)
            created_at = item.get("createdAt")
            posted_at = epoch_ms_to_iso(created_at)

            # Remote: workplaceType == "remote"
            remote: bool | None = None
            workplace_type = item.get("workplaceType")
            if workplace_type and isinstance(workplace_type, str):
                remote = (workplace_type.strip().lower() == "remote")

            # Salary range
            salary: str | None = None
            salary_range = item.get("salaryRange")
            if isinstance(salary_range, dict):
                min_v = salary_range.get("min")
                max_v = salary_range.get("max")
                curr = salary_range.get("currency") or ""
                interval = salary_range.get("interval") or ""
                if min_v is not None and max_v is not None:
                    salary = f"{curr} {min_v}-{max_v} / {interval}".strip()
                elif min_v is not None:
                    salary = f"{curr} {min_v} / {interval}".strip()
                elif max_v is not None:
                    salary = f"{curr} {max_v} / {interval}".strip()
            elif isinstance(salary_range, str) and salary_range.strip():
                salary = salary_range.strip()

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
