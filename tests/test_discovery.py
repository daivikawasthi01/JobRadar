"""Offline tests for ATS company discovery."""
import asyncio
import json

import pytest

from src.adapters.smartrecruiters import SmartRecruitersAdapter
from src.discovery import (
    DISCOVERY_ATS,
    DiscoveryManager,
    company_names_match,
    generate_slugs,
    load_input_companies,
)
from src.fetcher import NotFoundError


def test_generates_slug_candidates_for_names_with_punctuation():
    from src.discovery import normalize_company_name

    assert generate_slugs(normalize_company_name("D. E. Shaw")) == [
        "deshaw",
        "d-e-shaw",
        "deshawhq",
        "deshawinc",
    ]
    assert generate_slugs(normalize_company_name("Cult.fit")) == [
        "cultfit",
        "cult-fit",
        "cultfithq",
        "cultfitinc",
    ]


def test_name_comparison_normalizes_corporate_suffixes():
    assert company_names_match("Acme Inc.", "Acme")
    assert company_names_match("Acme Technologies", "ACME")
    assert not company_names_match("Acme", "Acme Holdings")
    assert not company_names_match("", "Acme")


def test_smartrecruiters_company_name_is_read_from_response_fixture():
    with open("tests/fixtures/smartrecruiters_sample.json", encoding="utf-8") as fixture:
        raw = json.load(fixture)

    assert SmartRecruitersAdapter.extract_board_name(raw) == "Delivery Hero"


def test_loads_all_seed_name_files_and_deduplicates(tmp_path, monkeypatch):
    config = tmp_path / "config"
    inputs = config / "inputs"
    inputs.mkdir(parents=True)
    (config / "seed_company_names.txt").write_text(
        "# main seed\nAcme Inc.\nNorthstar\n",
        encoding="utf-8",
    )
    (config / "seed_company_names_startups.txt").write_text(
        "Acme\nNew Startup\n",
        encoding="utf-8",
    )
    (config / "seed_company_names_linkedin.txt").write_text(
        "Northstar Labs\nLinkedIn Seed\n",
        encoding="utf-8",
    )
    (inputs / "more.txt").write_text("Input Company\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    companies = load_input_companies()

    assert [company["name"] for company in companies] == [
        "Acme Inc.",
        "Northstar",
        "LinkedIn Seed",
        "New Startup",
        "Input Company",
    ]


def test_discovery_targets_five_requested_ats():
    assert DISCOVERY_ATS == (
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "smartrecruiters",
    )


def test_careers_page_patterns_recognize_workable_and_smartrecruiters():
    from src.discovery import RE_SMARTRECRUITERS_LINK, RE_WORKABLE_LINK

    workable = RE_WORKABLE_LINK.search("https://apply.workable.com/acme/j/123")
    assert workable is not None and workable.group(1) == "acme"
    assert RE_SMARTRECRUITERS_LINK.search(
        "https://jobs.smartrecruiters.com/Acme/123"
    ).group(1).lower() == "acme"


class FakeAdapter:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def fetch(self, session, company, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return []


class FakeResponse:
    status = 200

    def __init__(self, board_name):
        self.board_name = board_name

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def json(self, content_type=None):
        return {"name": self.board_name}


class FakeSession:
    def __init__(self, board_name):
        self.board_name = board_name

    def get(self, url, timeout=None):
        return FakeResponse(self.board_name)


def make_manager(tmp_path):
    return DiscoveryManager(
        rps=1000,
        progress_path=str(tmp_path / "progress.json"),
        candidates_path=str(tmp_path / "candidates.csv"),
        unsupported_path=str(tmp_path / "unsupported.csv"),
        custom_pages_path=str(tmp_path / "custom.csv"),
    )


def test_zero_job_board_is_a_valid_discovery_and_resume_skips_it(tmp_path, monkeypatch):
    import src.discovery as discovery

    adapter = FakeAdapter()
    monkeypatch.setattr(discovery, "ADAPTERS", {"lever": adapter})
    manager = make_manager(tmp_path)

    first = asyncio.run(manager.probe_ats_slug(None, "Acme", "lever", "acme"))
    second = asyncio.run(manager.probe_ats_slug(None, "Acme", "lever", "acme"))

    assert first == {
        "name": "Acme",
        "ats": "lever",
        "slug": "acme",
        "job_count": 0,
        "india_job_count": 0,
        "board_name": "",
        "sample_url": "",
    }
    assert second is None
    assert adapter.calls == 1
    assert "Acme|lever|acme" in manager.progress


def test_transient_probe_failure_is_not_marked_complete(tmp_path, monkeypatch):
    import src.discovery as discovery

    adapter = FakeAdapter(error=RuntimeError("temporary timeout"))
    monkeypatch.setattr(discovery, "ADAPTERS", {"lever": adapter})
    manager = make_manager(tmp_path)

    result = asyncio.run(manager.probe_ats_slug(None, "Acme", "lever", "acme"))

    assert result is None
    assert "Acme|lever|acme" not in manager.progress
    assert adapter.calls == 1


def test_not_found_probe_is_marked_complete(tmp_path, monkeypatch):
    import src.discovery as discovery

    adapter = FakeAdapter(error=NotFoundError("not found"))
    monkeypatch.setattr(discovery, "ADAPTERS", {"lever": adapter})
    manager = make_manager(tmp_path)

    result = asyncio.run(manager.probe_ats_slug(None, "Acme", "lever", "acme"))

    assert result is None
    assert "Acme|lever|acme" in manager.progress


def test_greenhouse_slug_collision_is_rejected(tmp_path, monkeypatch):
    import src.discovery as discovery

    monkeypatch.setattr(discovery, "ADAPTERS", {"greenhouse": FakeAdapter()})
    manager = make_manager(tmp_path)

    result = asyncio.run(
        manager.probe_ats_slug(FakeSession("Acme Holdings"), "Acme", "greenhouse", "acme")
    )

    assert result is None
    assert "Acme|greenhouse|acme" in manager.progress


def test_empty_smartrecruiters_board_is_rejected(tmp_path, monkeypatch):
    """SmartRecruiters returns 200 with no postings for any slug, real or not."""
    import src.discovery as discovery

    class EmptySmartRecruiters(FakeAdapter):
        async def fetch_with_board_name(self, session, company, **kwargs):
            self.calls += 1
            return [], ""

    adapter = EmptySmartRecruiters()
    monkeypatch.setattr(discovery, "ADAPTERS", {"smartrecruiters": adapter})
    manager = make_manager(tmp_path)

    result = asyncio.run(manager.probe_ats_slug(None, "Acme", "smartrecruiters", "acme"))

    assert result is None
    assert adapter.calls == 1
    assert "Acme|smartrecruiters|acme" in manager.progress
