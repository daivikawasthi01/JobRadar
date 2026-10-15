"""Offline tests for Hacker News company-name extraction."""
import json
from pathlib import Path

import pytest

from src.hn_discovery import (
    HNDiscoveryError,
    extract_company_names,
    find_latest_thread,
    write_company_names,
)
from src.discovery import load_input_companies

FIXTURES_DIR = Path("tests/fixtures")


def load_fixture(name: str) -> dict:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def test_finds_latest_hiring_thread_not_who_wants_to_be_hired():
    thread = find_latest_thread(load_fixture("hn_monthly_search.json"))
    assert thread["objectID"] == "200"
    assert thread["title"] == "Ask HN: Who is hiring? (October 2026)"


def test_extracts_unique_names_from_top_level_comment_headers():
    names = extract_company_names(load_fixture("hn_monthly_item.json"))
    assert names == ["Acme AI", "Northstar Labs"]


def test_rejects_invalid_search_response():
    with pytest.raises(HNDiscoveryError, match="hits list"):
        find_latest_thread({"hits": None})


def test_rejects_item_without_top_level_comments():
    with pytest.raises(HNDiscoveryError, match="comments list"):
        extract_company_names({"type": "story", "children": None})


def test_writes_dated_input_file_for_discovery(tmp_path):
    thread = find_latest_thread(load_fixture("hn_monthly_search.json"))
    names = extract_company_names(load_fixture("hn_monthly_item.json"))

    path = write_company_names(thread, names, tmp_path)

    assert path.name == "hn_who_is_hiring_2026-10.txt"
    assert path.read_text(encoding="utf-8").splitlines() == [
        "# Generated from HN story 200: Ask HN: Who is hiring? (October 2026)",
        "Acme AI",
        "Northstar Labs",
    ]
    assert [company["name"] for company in load_input_companies([str(path)])] == names


def test_does_not_write_empty_company_list(tmp_path):
    thread = find_latest_thread(load_fixture("hn_monthly_search.json"))

    with pytest.raises(HNDiscoveryError, match="no parseable company names"):
        write_company_names(thread, [], tmp_path)
