"""Tests for src/textutil.py."""
import re
from src.textutil import epoch_ms_to_iso, html_to_text, normalize_iso, now_utc_iso


def test_html_to_text_none_and_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""
    assert html_to_text("   ") == ""


def test_html_to_text_greenhouse_escaped():
    # Greenhouse returns HTML-escaped content in its JSON API
    raw = "&lt;div&gt;&lt;p&gt;We are hiring a &lt;strong&gt;Software Engineer&lt;/strong&gt; &amp;amp; more!&lt;/p&gt;&lt;/div&gt;"
    cleaned = html_to_text(raw)
    assert cleaned == "We are hiring a Software Engineer & more!"
    assert "<" not in cleaned
    assert ">" not in cleaned


def test_html_to_text_whitespace_collapsing():
    raw = "<p>Line 1</p>\n\n   <p>Line   2  with   spaces</p>\t<div>Line 3</div>"
    cleaned = html_to_text(raw)
    assert cleaned == "Line 1 Line 2 with spaces Line 3"


def test_now_utc_iso():
    ts = now_utc_iso()
    assert ts.endswith("Z")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)


def test_epoch_ms_to_iso():
    assert epoch_ms_to_iso(None) is None
    assert epoch_ms_to_iso(-1000) is None
    assert epoch_ms_to_iso("invalid") is None

    # 1609459200000 ms is 2021-01-01T00:00:00Z
    assert epoch_ms_to_iso(1609459200000) == "2021-01-01T00:00:00Z"
    assert epoch_ms_to_iso(1609459200000.0) == "2021-01-01T00:00:00Z"


def test_normalize_iso():
    assert normalize_iso(None) is None
    assert normalize_iso("") is None
    assert normalize_iso("not-a-date") is None

    # UTC with Z
    assert normalize_iso("2026-10-12T04:30:00Z") == "2026-10-12T04:30:00Z"

    # With offset (IST UTC+5:30)
    assert normalize_iso("2026-10-12T10:00:00+05:30") == "2026-10-12T04:30:00Z"

    # With fractional seconds
    assert normalize_iso("2026-10-12T04:30:00.999Z") == "2026-10-12T04:30:00Z"

    # Naive ISO assumes UTC
    assert normalize_iso("2026-10-12T04:30:00") == "2026-10-12T04:30:00Z"
