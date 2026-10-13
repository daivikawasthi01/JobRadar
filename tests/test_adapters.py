"""Unit tests for ATS adapters using fixtures."""
import json
from pathlib import Path
import pytest
from src.adapters.ashby import AshbyAdapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.models import Company, Job

FIXTURES_DIR = Path("tests/fixtures")


@pytest.fixture
def sample_company():
    def _make(ats: str, slug: str, name: str = "TestCorp"):
        return Company(name=name, ats=ats, slug=slug, tier=1)
    return _make


def test_greenhouse_adapter(sample_company):
    comp = sample_company("greenhouse", "stripe", "Stripe")
    adapter = GreenhouseAdapter()

    fixture_path = FIXTURES_DIR / "greenhouse_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("greenhouse:stripe:")
        assert job.company == "Stripe"
        assert job.company_key == "greenhouse:stripe"
        assert job.title and len(job.title) > 0
        assert job.url and job.url.startswith("http")
        assert "<" not in job.description
        assert "&lt;" not in job.description
        if job.posted_at:
            assert job.posted_at.endswith("Z")

    # Deliberately malformed entry skipped without raising
    malformed_data = {
        "jobs": [
            {"id": None, "title": "Missing ID"},
            {"id": 123, "title": ""},  # empty title
            {"id": 456, "title": "Valid Job", "absolute_url": ""},  # empty URL
            {"not_a_job": True},
            "string_instead_of_dict",
            {
                "id": 999,
                "title": "Good Job",
                "absolute_url": "https://example.com/job/999",
                "content": "&lt;p&gt;Good content&lt;/p&gt;",
            },
        ]
    }
    handled_jobs = adapter.parse(malformed_data, comp)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "greenhouse:stripe:999"


def test_lever_adapter(sample_company):
    comp = sample_company("lever", "palantir", "Palantir")
    adapter = LeverAdapter()

    fixture_path = FIXTURES_DIR / "lever_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("lever:palantir:")
        assert job.company == "Palantir"
        assert job.company_key == "lever:palantir"
        assert job.title and len(job.title) > 0
        assert job.url and job.url.startswith("http")
        assert "<" not in job.description
        assert "&lt;" not in job.description
        if job.posted_at:
            assert job.posted_at.endswith("Z")

    # Deliberately malformed entry skipped without raising
    malformed_data = [
        {"id": None, "text": "No ID"},
        {"id": "abc", "text": "", "hostedUrl": "https://example.com"},
        {"id": "def", "text": "No URL", "hostedUrl": ""},
        "not_a_dict",
        {
            "id": "lever-good-1",
            "text": "Software Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/lever-good-1",
            "description": "<div>Clean &amp; good</div>",
            "categories": {"location": "London, UK"},
            "createdAt": 1609459200000,
            "workplaceType": "remote",
        },
    ]
    handled_jobs = adapter.parse(malformed_data, comp)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "lever:palantir:lever-good-1"
    assert handled_jobs[0].remote is True
    assert handled_jobs[0].posted_at == "2021-01-01T00:00:00Z"
    assert "<" not in handled_jobs[0].description


def test_ashby_adapter(sample_company):
    comp = sample_company("ashby", "ramp", "Ramp")
    adapter = AshbyAdapter()

    fixture_path = FIXTURES_DIR / "ashby_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("ashby:ramp:")
        assert job.company == "Ramp"
        assert job.company_key == "ashby:ramp"
        assert job.title and len(job.title) > 0
        assert job.url and job.url.startswith("http")
        assert "<" not in job.description
        assert "&lt;" not in job.description
        if job.posted_at:
            assert job.posted_at.endswith("Z")

    # Deliberately malformed entry skipped and unlisted skipped
    malformed_data = {
        "jobs": [
            {"id": "unlisted-1", "title": "Secret Job", "jobUrl": "https://example.com/1", "isListed": False},
            {"id": None, "title": "Missing ID"},
            {"id": "no-url", "title": "Missing URL", "jobUrl": ""},
            {"id": "no-title", "title": "", "jobUrl": "https://example.com/2"},
            123,
            {
                "id": "ashby-good-1",
                "title": "Backend Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/ramp/ashby-good-1",
                "isListed": True,
                "isRemote": True,
                "descriptionHtml": "<p>Ashby &lt;description&gt;</p>",
                "compensation": {"compensationTierSummary": "$150K - $180K"},
            },
        ]
    }
    handled_jobs = adapter.parse(malformed_data, comp)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "ashby:ramp:ashby-good-1"
    assert handled_jobs[0].remote is True
    assert handled_jobs[0].salary == "$150K - $180K"
    assert "<" not in handled_jobs[0].description
    assert "&lt;" not in handled_jobs[0].description
