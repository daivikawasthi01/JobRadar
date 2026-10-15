"""Offline tests for Common Crawl ATS slug harvesting."""
import asyncio
import csv
import json
from pathlib import Path

import pytest

from src.models import Job
from scripts import harvest_slugs


def test_extracts_job_board_slugs_only_from_supported_job_urls():
    cases = [
        ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
        ("https://jobs.lever.co/acme/123", "lever", "acme"),
        ("https://jobs.ashbyhq.com/acme/123", "ashby", "acme"),
        ("https://apply.workable.com/acme/j/123", "workable", "acme"),
        ("https://jobs.smartrecruiters.com/Acme/123", "smartrecruiters", "acme"),
        ("https://boards.greenhouse.io/acme", "greenhouse", None),
        ("https://boards.greenhouse.io/embed/job_board?for=acme", "greenhouse", None),
        ("https://example.com/acme/jobs/123", "greenhouse", None),
    ]
    for url, ats, expected in cases:
        assert harvest_slugs.parse_board_slug(url, ats) == expected


def test_prefix_partitions_cover_mixed_case_board_slugs():
    assert set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_") == set(
        harvest_slugs.PREFIX_CHARS
    )


def test_parses_paging_metadata_and_ndjson_records():
    assert harvest_slugs.parse_index_metadata('{"pages": 2, "pageSize": 5}') == 2
    assert harvest_slugs.parse_index_metadata('{"pages": 0}') == 0
    assert harvest_slugs.parse_index_records(
        '{"url":"https://jobs.lever.co/acme/123"}\n{"url":"https://jobs.lever.co/beta/234"}\n'
    ) == [
        "https://jobs.lever.co/acme/123",
        "https://jobs.lever.co/beta/234",
    ]
    with pytest.raises(harvest_slugs.HarvestError, match="pages"):
        harvest_slugs.parse_index_metadata("{}")


def test_harvests_pages_and_persists_pending_slugs(tmp_path):
    calls = []

    def fake_request(api_url, parameters, limiter, timeout, retries):
        calls.append(parameters.copy())
        if parameters.get("showNumPages") == "true":
            return '{"pages": 2}'
        if parameters["page"] == 0:
            return '{"url":"https://jobs.lever.co/acme/123"}'
        return '{"url":"https://jobs.lever.co/beta/234"}'

    cache_path = tmp_path / "cache.json"
    manager = harvest_slugs.CommonCrawlHarvester(
        cache_path,
        rps=1000,
        request=fake_request,
    )
    manager.harvest_prefix(
        "CC-MAIN-TEST",
        "https://index.example/cc-index",
        "lever",
        "jobs.lever.co",
        "a",
    )

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(calls) == 3
    assert cache["completed_prefixes"] == [
        "CC-MAIN-TEST|lever|jobs.lever.co|a"
    ]
    assert set(cache["pending"]) == {"lever:acme", "lever:beta"}


def test_failed_prefix_is_subdivided_and_retryable(tmp_path):
    def fake_request(api_url, parameters, limiter, timeout, retries):
        if parameters["url"].endswith("/a*"):
            raise harvest_slugs.HarvestError("temporary index timeout")
        return '{"pages": 0}' if parameters.get("showNumPages") == "true" else ""

    cache_path = tmp_path / "cache.json"
    manager = harvest_slugs.CommonCrawlHarvester(
        cache_path,
        rps=1000,
        request=fake_request,
    )
    manager.harvest_prefix(
        "CC-MAIN-TEST",
        "https://index.example/cc-index",
        "lever",
        "jobs.lever.co",
        "a",
    )

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "CC-MAIN-TEST|lever|jobs.lever.co|a" in cache["split_prefixes"]
    assert "CC-MAIN-TEST|lever|jobs.lever.co|aa" in cache["completed_prefixes"]
    assert not cache["unresolved_prefixes"]


class FakeAdapter:
    def __init__(self, jobs):
        self.jobs = jobs

    async def fetch(self, session, company, **kwargs):
        return self.jobs


def make_job(title, location):
    return Job(
        job_id="fixture:1",
        company_key="fixture:company",
        company="Fixture",
        ats="fixture",
        title=title,
        location=location,
        url="https://example.com/job",
        description="",
        posted_at=None,
        salary=None,
        remote=None,
    )


def test_screening_accepts_india_or_intern_title_and_caches_rejections(tmp_path, monkeypatch):
    companies_path = tmp_path / "companies.csv"
    companies_path.write_text(
        "# sample config\nname,ats,slug,tier\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "cache.json"
    cache = harvest_slugs.load_cache(cache_path)
    cache["pending"] = {
        "greenhouse:india-board": {
            "ats": "greenhouse",
            "slug": "india-board",
            "crawl_ids": ["CC-MAIN-TEST"],
        },
        "lever:intern-board": {
            "ats": "lever",
            "slug": "intern-board",
            "crawl_ids": ["CC-MAIN-TEST"],
        },
        "ashby:irrelevant-board": {
            "ats": "ashby",
            "slug": "irrelevant-board",
            "crawl_ids": ["CC-MAIN-TEST"],
        },
    }
    harvest_slugs.save_cache(cache_path, cache)

    adapters = {
        "greenhouse": FakeAdapter([make_job("Engineer", "Bengaluru, India")]),
        "lever": FakeAdapter([make_job("Software Intern", "Remote, US")]),
        "ashby": FakeAdapter([make_job("Marketing Manager", "New York, NY")]),
    }
    monkeypatch.setattr(harvest_slugs, "ADAPTERS", adapters)
    manager = harvest_slugs.CommonCrawlHarvester(cache_path)

    accepted, rejected, errors = asyncio.run(
        harvest_slugs.screen_pending(
            manager,
            companies_path,
            max_screened=10,
            rps=1000.0,
        )
    )

    with companies_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.reader(source))
    assert accepted == 2
    assert rejected == 1
    assert errors == 0
    assert rows[-2:] == [
        ["India Board", "greenhouse", "india-board", "2"],
        ["Intern Board", "lever", "intern-board", "3"],
    ]
    updated_cache = harvest_slugs.load_cache(cache_path)
    assert updated_cache["screened"]["ashby:irrelevant-board"]["status"] == "rejected"
    assert not updated_cache["pending"]
