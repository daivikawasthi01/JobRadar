"""Adapter for public, server-rendered Breezy HR career pages."""
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


class BreezyAdapter:
    ats: str = "breezy"

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
            raise ValueError(f"Invalid Breezy board slug for {company.key}")

        raw = await get_text(
            session,
            f"https://{company.slug}.breezy.hr/",
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Parse job titles and location labels from the public board HTML."""
        if not isinstance(raw, str):
            logger.warning("Breezy response for %s is not HTML text", company.key)
            return []

        board_url = f"https://{company.slug}.breezy.hr/"
        board_host = urlsplit(board_url).hostname
        soup = BeautifulSoup(raw, "html.parser")
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for anchor in soup.select("a[href]"):
            try:
                job_url = urljoin(board_url, anchor["href"])
                parsed_url = urlsplit(job_url)
            except (KeyError, ValueError):
                continue

            path_parts = parsed_url.path.strip("/").split("/")
            if (
                parsed_url.scheme != "https"
                or parsed_url.hostname != board_host
                or len(path_parts) != 2
                or path_parts[0] != "p"
                or not path_parts[1]
            ):
                continue

            title_node = anchor.find(["h1", "h2", "h3", "h4"])
            title = title_node.get_text(" ", strip=True) if title_node else ""
            if not title:
                continue

            native_id = unquote(path_parts[1])
            if native_id in seen_ids:
                continue
            seen_ids.add(native_id)

            location_node = anchor.select_one("li.location span")
            location = location_node.get_text(" ", strip=True) if location_node else ""

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
                    remote=None,
                )
            )

        return jobs
