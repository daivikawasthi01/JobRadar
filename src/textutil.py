"""Text and datetime normalization utilities for JobRadar."""
from datetime import datetime, timezone
import html
import re
from bs4 import BeautifulSoup


def html_to_text(s: str | None) -> str:
    """Convert HTML content to clean, single-line plain text.

    Steps:
    1. None -> ""
    2. html.unescape (decodes entities such as &lt; &gt; &amp;)
    3. Parse with BeautifulSoup ("html.parser")
    4. get_text(" ")
    5. Collapse multiple whitespace characters into a single space
    6. Strip leading/trailing whitespace
    """
    if s is None:
        return ""
    unescaped = html.unescape(s)
    soup = BeautifulSoup(unescaped, "html.parser")
    text = soup.get_text(" ")
    collapsed = re.sub(r"\s+", " ", text)
    return collapsed.strip()


def now_utc_iso() -> str:
    """Return current UTC timestamp in ISO-8601 with seconds precision ending in 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_ms_to_iso(ms: int | float | None) -> str | None:
    """Convert epoch milliseconds to UTC ISO-8601 string ending in 'Z'."""
    if ms is None:
        return None
    try:
        val = float(ms)
        if val < 0:
            return None
        dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError):
        return None


def normalize_iso(s: str | None) -> str | None:
    """Normalize any ISO-8601 datetime string to UTC ISO-8601 ending in 'Z'."""
    if not s or not isinstance(s, str):
        return None
    try:
        # datetime.fromisoformat supports 'Z' in Python 3.11+
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
