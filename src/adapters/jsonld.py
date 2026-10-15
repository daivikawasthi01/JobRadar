"""Schema.org JSON-LD JobPosting adapter for public careers pages."""
import hashlib
import json
import logging
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup

from src.fetcher import get_text
from src.models import Company, Job
from src.textutil import html_to_text, normalize_iso

logger = logging.getLogger(__name__)


def _is_absolute_http_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _is_job_posting(value: dict[str, Any]) -> bool:
    schema_type = value.get("@type")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    return any(
        isinstance(item, str) and item.rsplit("/", 1)[-1].casefold() == "jobposting"
        for item in types
    )


def _job_postings(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if _is_job_posting(value):
            yield value
        for child in value.values():
            yield from _job_postings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _job_postings(child)


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "value"):
            text = _text_value(value.get(key))
            if text:
                return text
    return ""


def _location_text(value: Any) -> str:
    places = value if isinstance(value, list) else [value]
    locations: list[str] = []
    seen: set[str] = set()
    for place in places:
        if isinstance(place, str):
            parts = [place.strip()]
        elif isinstance(place, dict):
            address = place.get("address")
            if isinstance(address, dict):
                parts = [
                    _text_value(address.get(key))
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                ]
            elif isinstance(address, str):
                parts = [address.strip()]
            else:
                parts = [_text_value(place.get("name"))]
        else:
            continue

        normalized_parts: list[str] = []
        part_seen: set[str] = set()
        for part in parts:
            if part and part.casefold() not in part_seen:
                normalized_parts.append(part)
                part_seen.add(part.casefold())
        location = ", ".join(normalized_parts)
        if location and location.casefold() not in seen:
            locations.append(location)
            seen.add(location.casefold())
    return "; ".join(locations)


def _salary_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None

    currency = _text_value(value.get("currency"))
    amount = value.get("value")
    unit = ""
    if isinstance(amount, dict):
        minimum = _text_value(amount.get("minValue"))
        maximum = _text_value(amount.get("maxValue"))
        single = _text_value(amount.get("value"))
        unit = _text_value(amount.get("unitText"))
        if minimum and maximum:
            amount_text = f"{minimum}-{maximum}"
        else:
            amount_text = minimum or maximum or single
    else:
        amount_text = _text_value(amount)

    parts = [part for part in (currency, amount_text) if part]
    salary = " ".join(parts)
    if unit:
        salary = f"{salary} / {unit}".strip()
    return salary or None


class JsonLdAdapter:
    ats: str = "jsonld"

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        company: Company,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        semaphore: Any = None,
    ) -> list[Job]:
        url = company.extra.strip() if isinstance(company.extra, str) else ""
        if not _is_absolute_http_url(url):
            raise ValueError(
                f"JSON-LD company {company.key} requires an absolute page URL in its extra field."
            )

        raw = await get_text(
            session,
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            semaphore=semaphore,
        )
        return self.parse(raw, company)

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Parse JobPosting objects from JSON-LD scripts in an HTML page."""
        if not isinstance(raw, str):
            logger.warning("JSON-LD response for %s is not HTML text", company.key)
            return []

        soup = BeautifulSoup(raw, "html.parser")
        scripts = soup.find_all("script", attrs={"type": self._is_jsonld_type})
        listing_url = company.extra.strip() if isinstance(company.extra, str) else ""
        jobs: list[Job] = []
        seen_ids: set[str] = set()
        malformed_blocks = 0

        for script in scripts:
            script_text = script.string or script.get_text()
            if not script_text.strip():
                continue
            try:
                data = json.loads(script_text)
            except json.JSONDecodeError:
                malformed_blocks += 1
                continue

            for posting in _job_postings(data):
                title = posting.get("title")
                if not isinstance(title, str) or not title.strip():
                    logger.warning("Skipping JSON-LD posting for %s with no title", company.key)
                    continue

                raw_url = posting.get("url")
                target_url = raw_url.strip() if isinstance(raw_url, str) and raw_url.strip() else listing_url
                try:
                    job_url = urljoin(listing_url, target_url)
                except ValueError:
                    job_url = ""
                if not _is_absolute_http_url(job_url):
                    logger.warning("Skipping JSON-LD posting for %s with no valid URL", company.key)
                    continue

                identifier = posting.get("identifier")
                native_id = (
                    _text_value(identifier.get("value"))
                    if isinstance(identifier, dict)
                    else ""
                )
                if not native_id:
                    native_id = hashlib.sha1(job_url.encode("utf-8")).hexdigest()[:12]
                job_id = f"{self.ats}:{company.slug}:{native_id}"
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                description = posting.get("description")
                jobs.append(
                    Job(
                        job_id=job_id,
                        company_key=company.key,
                        company=company.name,
                        ats=self.ats,
                        title=title.strip(),
                        location=_location_text(posting.get("jobLocation")),
                        url=job_url,
                        description=html_to_text(description if isinstance(description, str) else ""),
                        posted_at=normalize_iso(posting.get("datePosted")),
                        salary=_salary_text(posting.get("baseSalary")),
                        remote=None,
                    )
                )

        if not jobs:
            suffix = f"; skipped {malformed_blocks} malformed block(s)" if malformed_blocks else ""
            logger.warning("No JobPosting JSON-LD found for %s%s", company.key, suffix)
        elif malformed_blocks:
            logger.warning(
                "Skipped %d malformed JSON-LD block(s) for %s",
                malformed_blocks,
                company.key,
            )
        return jobs

    @staticmethod
    def _is_jsonld_type(value: Any) -> bool:
        return (
            isinstance(value, str)
            and value.split(";", 1)[0].strip().casefold() == "application/ld+json"
        )
