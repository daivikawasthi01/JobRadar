"""Extract company names from the monthly Hacker News hiring thread."""
import asyncio
from datetime import datetime, timezone
import html
import json
import logging
from pathlib import Path
import re

import aiohttp
from bs4 import BeautifulSoup

from src.discovery import normalize_company_name

logger = logging.getLogger("jobradar.hn_discovery")

SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story,author_whoishiring&query=Who%20is%20hiring"
)
ITEM_URL = "https://hn.algolia.com/api/v1/items/{story_id}"
USER_AGENT = "JobRadar/1.0 (monthly company discovery)"
THREAD_TITLE = re.compile(r"\bwho\s+is\s+hiring\b", re.IGNORECASE)
HTML_TAG = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)


class HNDiscoveryError(Exception):
    """Raised when the monthly Hacker News thread cannot be processed."""


def find_latest_thread(search_data: object) -> dict:
    """Return the newest "Who is hiring?" story from an Algolia search response."""
    if not isinstance(search_data, dict) or not isinstance(search_data.get("hits"), list):
        raise HNDiscoveryError("HN search response is missing its hits list.")

    candidates = [
        hit
        for hit in search_data["hits"]
        if isinstance(hit, dict)
        and hit.get("author") == "whoishiring"
        and isinstance(hit.get("title"), str)
        and THREAD_TITLE.search(hit["title"])
        and isinstance(hit.get("objectID"), str)
        and str(hit.get("created_at_i", "")).isdigit()
    ]
    if not candidates:
        raise HNDiscoveryError('No "Who is hiring?" monthly thread was found.')
    return max(candidates, key=lambda hit: int(hit["created_at_i"]))


def _first_line(comment_text: str) -> str:
    text = html.unescape(comment_text)
    if not HTML_TAG.search(text):
        return next((line.strip() for line in text.splitlines() if line.strip()), "")
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["br", "p", "div", "li"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return next((line.strip() for line in soup.get_text().splitlines() if line.strip()), "")


def _company_from_line(line: str) -> str | None:
    for separator in ("|", " — ", " – "):
        if separator in line:
            company = line.split(separator, maxsplit=1)[0]
            company = company.strip().strip("*_` ").lstrip("-• ").strip()
            return company or None
    return None


def extract_company_names(item_data: object) -> list[str]:
    """Extract unique company names from top-level comments in an Algolia item."""
    if not isinstance(item_data, dict) or item_data.get("type") != "story":
        raise HNDiscoveryError("HN item response is not a story.")
    children = item_data.get("children")
    if not isinstance(children, list):
        raise HNDiscoveryError("HN story response is missing its comments list.")

    names: list[str] = []
    seen: set[str] = set()
    for comment in children:
        if (
            not isinstance(comment, dict)
            or comment.get("type") != "comment"
            or comment.get("dead")
            or comment.get("deleted")
            or not isinstance(comment.get("text"), str)
        ):
            continue
        name = _company_from_line(_first_line(comment["text"]))
        if not name:
            continue
        normalized = normalize_company_name(name).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            names.append(name)
    return names


async def _get_json(session: aiohttp.ClientSession, url: str) -> object:
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
        raise HNDiscoveryError(f"Could not fetch Hacker News data from {url}: {exc}") from exc


def _output_path(thread: dict, output_dir: str | Path) -> Path:
    try:
        posted_at = datetime.fromtimestamp(int(thread["created_at_i"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
        raise HNDiscoveryError("HN thread has an invalid creation timestamp.") from exc
    return Path(output_dir) / f"hn_who_is_hiring_{posted_at:%Y-%m}.txt"


def write_company_names(thread: dict, names: list[str], output_dir: str | Path) -> Path:
    """Write the generated names file consumed by the default `discover` inputs."""
    if not names:
        raise HNDiscoveryError("The latest HN thread contained no parseable company names.")
    story_id = thread.get("objectID")
    title = thread.get("title")
    if not isinstance(story_id, str) or not isinstance(title, str):
        raise HNDiscoveryError("HN thread is missing its story ID or title.")

    path = _output_path(thread, output_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# Generated from HN story {story_id}: {title}\n" + "\n".join(names) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise HNDiscoveryError(f"Could not write HN company names to {path}: {exc}") from exc
    return path


async def run_hn_discovery(output_dir: str | Path = "config/inputs") -> tuple[Path, int]:
    """Fetch the current monthly thread and save its company names."""
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        search_data = await _get_json(session, SEARCH_URL)
        thread = find_latest_thread(search_data)
        item_data = await _get_json(session, ITEM_URL.format(story_id=thread["objectID"]))

    names = extract_company_names(item_data)
    path = write_company_names(thread, names, output_dir)
    logger.info(
        'Extracted %d company names from "%s" into %s',
        len(names),
        thread["title"],
        path,
    )
    return path, len(names)
