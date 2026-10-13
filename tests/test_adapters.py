"""Unit tests for ATS adapters using fixtures."""
import json
from pathlib import Path
import pytest
from src.adapters.ashby import AshbyAdapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.adapters.smartrecruiters import SmartRecruitersAdapter
from src.adapters.workable import WorkableAdapter
from src.adapters.workday import WorkdayAdapter
from src.models import Company, Job
from src.registry import load_companies

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


def test_smartrecruiters_adapter(sample_company):
    comp = sample_company("smartrecruiters", "deliveryhero", "Delivery Hero")
    adapter = SmartRecruitersAdapter()

    fixture_path = FIXTURES_DIR / "smartrecruiters_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("smartrecruiters:deliveryhero:")
        assert job.company == "Delivery Hero"
        assert job.company_key == "smartrecruiters:deliveryhero"
        assert job.title and len(job.title) > 0
        assert job.url and job.url.startswith("https://jobs.smartrecruiters.com/deliveryhero/")
        if job.posted_at:
            assert job.posted_at.endswith("Z")

    # Deliberately malformed entry skipped without raising
    malformed_data = {
        "content": [
            {"id": None, "name": "No ID"},
            {"id": "sr-1", "name": ""},
            {"id": "sr-2", "name": "   "},
            "not_a_dict",
            {
                "id": "744000155305309",
                "name": "Fullstack Engineer",
                "releasedDate": "2026-10-13T15:46:40.475Z",
                "location": {
                    "city": "Berlin",
                    "country": "Germany",
                    "fullLocation": "Berlin, Germany",
                    "remote": False,
                },
            },
        ]
    }
    handled_jobs = adapter.parse(malformed_data, comp)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "smartrecruiters:deliveryhero:744000155305309"
    assert handled_jobs[0].title == "Fullstack Engineer"
    assert handled_jobs[0].location == "Berlin, Germany"
    assert handled_jobs[0].remote is False


def test_workable_adapter(sample_company):
    comp = sample_company("workable", "fortanix", "Fortanix")
    adapter = WorkableAdapter()

    fixture_path = FIXTURES_DIR / "workable_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("workable:fortanix:")
        assert job.company == "Fortanix"
        assert job.company_key == "workable:fortanix"
        assert job.title and len(job.title) > 0
        assert job.url and job.url.startswith("https://apply.workable.com/fortanix/j/")

    # Deliberately malformed entry skipped without raising
    malformed_data = {
        "results": [
            {"id": None, "title": "Missing ID"},
            {"shortcode": "", "title": "Empty shortcode"},
            {"shortcode": "ABC", "title": ""},
            123,
            {
                "shortcode": "GOOD123",
                "title": "Security Engineer",
                "remote": True,
                "location": {"city": "Mountain View", "country": "United States"},
                "published": "2026-10-10T12:00:00Z",
            },
        ]
    }
    handled_jobs = adapter.parse(malformed_data, comp)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "workable:fortanix:GOOD123"
    assert handled_jobs[0].title == "Security Engineer"
    assert handled_jobs[0].remote is True
    assert handled_jobs[0].location == "Mountain View, United States"


def test_workday_adapter():
    comp_url = Company(
        name="NVIDIA",
        ats="workday",
        slug="nvidia",
        tier=1,
        extra="https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
    )
    adapter = WorkdayAdapter()

    fixture_path = FIXTURES_DIR / "workday_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    jobs = adapter.parse(raw_data, comp_url)
    assert len(jobs) >= 1

    for job in jobs:
        assert isinstance(job, Job)
        assert job.job_id.startswith("workday:nvidia:")
        assert job.company == "NVIDIA"
        assert job.company_key == "workday:nvidia"
        assert job.title and len(job.title) > 0
        assert job.url.startswith("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/")

    # Also test alternative extra format: site=...;wd=...
    comp_semi = Company(
        name="NVIDIA",
        ats="workday",
        slug="nvidia",
        tier=1,
        extra="site=NVIDIAExternalCareerSite;wd=wd5",
    )
    api_url, base_web, site = adapter._resolve_endpoints(comp_semi)
    assert api_url == "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
    assert base_web == "https://nvidia.wd5.myworkdayjobs.com"
    assert site == "NVIDIAExternalCareerSite"

    # Deliberately malformed entry skipped without raising
    malformed_data = {
        "jobPostings": [
            {"title": "", "externalPath": "/job/123"},
            {"title": "No Path"},
            {"externalPath": "/job/no_title"},
            None,
            {
                "title": "Senior AI Architect",
                "externalPath": "/job/US-CA-Santa-Clara/Senior-AI-Architect_JR123456",
                "locationsText": "Santa Clara, CA",
            },
        ]
    }
    handled_jobs = adapter.parse(malformed_data, comp_url)
    assert len(handled_jobs) == 1
    assert handled_jobs[0].job_id == "workday:nvidia:JR123456"
    assert handled_jobs[0].title == "Senior AI Architect"
    assert handled_jobs[0].location == "Santa Clara, CA"
    assert handled_jobs[0].url == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-AI-Architect_JR123456"


def test_registry_with_extra_column(tmp_path):
    csv_file = tmp_path / "companies.csv"
    csv_file.write_text(
        "name,ats,slug,tier,extra\n"
        "NVIDIA,workday,nvidia,1,https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs\n"
        "Delivery Hero,smartrecruiters,deliveryhero,2,\n"
        "Fortanix,workable,fortanix,2,\n",
        encoding="utf-8",
    )
    comps = load_companies(csv_file, allow_extra=True)
    assert len(comps) == 3
    assert comps[0].ats == "workday"
    assert comps[0].extra == "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
    assert comps[1].ats == "smartrecruiters"
    assert comps[1].extra is None
    assert comps[2].ats == "workable"
