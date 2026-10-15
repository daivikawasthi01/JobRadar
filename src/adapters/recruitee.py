"""Adapter for public Recruitee careers pages."""
import logging
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup

from src.fetcher import get_text
from src.models import Company, Job

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"^[a-z0-9-]+$", re.IGNORECASE)
_LOCATION_CLASSES = (
    "custom-css-style-job-location-city",
    "custom-css-style-job-location-region",
    "custom-css-style-job-location-country",
)
_WORKPLACE_LABELS = {
    "hybrid": None,
    "on-site": False,
    "onsite": False,
    "remote": True,
}


class RecruiteeAdapter:
    ats: str = "recruitee"

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
            raise ValueError(f"Invalid Recruitee board slug for {company.key}")

        raw = await get_text(
            session,
            f"https://{company.slug}.recruitee.com/",
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Parse the server-rendered job cards from a Recruitee careers page."""
        if not isinstance(raw, str):
            logger.warning("Recruitee response for %s is not HTML text", company.key)
            return []

        board_url = f"https://{company.slug}.recruitee.com/"
        board_host = urlsplit(board_url).hostname
        soup = BeautifulSoup(raw, "html.parser")
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            title = anchor.get_text(" ", strip=True)
            if not title or title.casefold() == "view job":
                continue

            job_url = urljoin(board_url, anchor["href"])
            parsed_url = urlsplit(job_url)
            path_parts = parsed_url.path.strip("/").split("/")
            if (
                parsed_url.hostname != board_host
                or parsed_url.scheme != "https"
                or len(path_parts) != 2
                or path_parts[0] != "o"
                or not path_parts[1]
            ):
                continue

            native_id = unquote(path_parts[1])
            if native_id in seen_ids:
                continue
            seen_ids.add(native_id)

            card = anchor.find_parent("div")
            location = ""
            workplace: bool | None = None
            if card is not None:
                location_parts = []
                for class_name in _LOCATION_CLASSES:
                    node = card.select_one(f".{class_name}")
                    if node:
                        value = node.get_text(" ", strip=True)
                        if value and value.casefold() not in {
                            part.casefold() for part in location_parts
                        }:
                            location_parts.append(value)
                location = ", ".join(location_parts)

                for span in card.find_all("span"):
                    label = span.get_text(" ", strip=True).casefold()
                    if label in _WORKPLACE_LABELS:
                        workplace = _WORKPLACE_LABELS[label]
                        break

            jobs.append(
                Job(
                    job_id=f"{self.ats}:{company.slug}:{native_id}",
                    company_key=company.key,
                    company=company.name,
                    ats=self.ats,
                    title=title,
                    location=location,
                    url=job_url,
                    description="",
                    posted_at=None,
                    salary=None,
                    remote=workplace,
                )
            )

        return jobs
