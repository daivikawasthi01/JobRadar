"""Unit tests for ATS adapters using fixtures."""
import asyncio
import json
from pathlib import Path
import pytest
from src.adapters.ashby import AshbyAdapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.adapters.smartrecruiters import SmartRecruitersAdapter
from src.adapters.workable import WorkableAdapter
from src.adapters.workday import WorkdayAdapter
from src.adapters.jsonld import JsonLdAdapter
from src.adapters.recruitee import RecruiteeAdapter
from src.adapters import ADAPTERS
from src.adapters.bamboohr import BambooHRAdapter
from src.adapters.breezy import BreezyAdapter
from src.fetcher import FetchError, NotFoundError
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


def test_jsonld_adapter():
    page_url = "https://www.anantaxtechnologies.com/jobs/reactjs-developer-intern-in-rajkot"
    comp = Company(
        name="AnantaX Technologies",
        ats="jsonld",
        slug="anantax",
        tier=2,
        extra=page_url,
    )
    adapter = JsonLdAdapter()
    fixture_path = FIXTURES_DIR / "jsonld_sample.html"
    raw_html = fixture_path.read_text(encoding="utf-8")

    jobs = adapter.parse(raw_html, comp)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_id == "jsonld:anantax:reactjs-developer-internship-rajkot-india"
    assert job.company_key == "jsonld:anantax"
    assert job.title == "React.js Developer"
    assert job.location == "Rajkot, Gujarat, India"
    assert job.url == page_url
    assert job.posted_at == "2026-10-12T00:00:00Z"
    assert job.salary == "INR 120000-300000 / YEAR"
    assert job.description == ""


def test_recruitee_adapter_parses_server_rendered_board():
    comp = Company(name="TestCorp", ats="recruitee", slug="testcorp", tier=2)
    raw_html = (FIXTURES_DIR / "recruitee_sample.html").read_text(encoding="utf-8")

    jobs = RecruiteeAdapter().parse(raw_html, comp)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_id == "recruitee:testcorp:software-engineer-intern"
    assert job.company_key == "recruitee:testcorp"
    assert job.title == "Software Engineer Intern"
    assert job.location == "Bengaluru, Karnataka, India"
    assert job.url == "https://testcorp.recruitee.com/o/software-engineer-intern"
    assert job.remote is False
    assert job.description == ""
    assert job.posted_at is None
    assert job.salary is None
    assert ADAPTERS["recruitee"].ats == "recruitee"


def test_recruitee_adapter_fetch_uses_configured_board_and_shared_fetcher():
    comp = Company(name="TestCorp", ats="recruitee", slug="testcorp", tier=2)
    fixture_html = (FIXTURES_DIR / "recruitee_sample.html").read_text(encoding="utf-8")
    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return fixture_html

    class FakeSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

    jobs = asyncio.run(RecruiteeAdapter().fetch(FakeSession(), comp, retries=0))

    assert len(jobs) == 1
    assert calls[0][0:2] == ("GET", "https://testcorp.recruitee.com/")
    assert calls[0][2]["timeout"].total == 15.0


def test_recruitee_fetch_rejects_invalid_slug():
    comp = Company(name="TestCorp", ats="recruitee", slug="bad/slug", tier=2)
    with pytest.raises(ValueError, match="Invalid Recruitee board slug"):
        asyncio.run(RecruiteeAdapter().fetch(None, comp))


def test_bamboohr_adapter_parses_public_listing_fixture():
    comp = Company(name="TestCorp", ats="bamboohr", slug="testcorp", tier=2)
    raw = json.loads((FIXTURES_DIR / "bamboohr_sample.json").read_text(encoding="utf-8"))

    jobs = BambooHRAdapter().parse(raw, comp)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.job_id == "bamboohr:testcorp:2401"
    assert first.company_key == "bamboohr:testcorp"
    assert first.title == "Software Engineer Intern"
    assert first.location == "Bengaluru, Karnataka"
    assert first.url == "https://testcorp.bamboohr.com/careers/2401"
    assert first.remote is False
    assert first.description == ""
    assert first.posted_at is None
    assert first.salary is None
    assert ADAPTERS["bamboohr"].ats == "bamboohr"


def test_bamboohr_adapter_skips_malformed_entries_and_duplicate_ids():
    comp = Company(name="TestCorp", ats="bamboohr", slug="testcorp", tier=2)
    raw = {
        "result": [
            {"id": None, "jobOpeningName": "Missing ID"},
            {"id": "1", "jobOpeningName": ""},
            {"id": "2", "jobOpeningName": "Good Role"},
            {"id": "2", "jobOpeningName": "Duplicate ID"},
        ]
    }

    jobs = BambooHRAdapter().parse(raw, comp)

    assert len(jobs) == 1
    assert jobs[0].url == "https://testcorp.bamboohr.com/careers/2"


def test_bamboohr_adapter_fetch_uses_public_careers_list_endpoint():
    comp = Company(name="TestCorp", ats="bamboohr", slug="testcorp", tier=2)
    fixture_json = (FIXTURES_DIR / "bamboohr_sample.json").read_text(encoding="utf-8")
    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def json(self, content_type=None):
            return json.loads(fixture_json)

    class FakeSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

    jobs = asyncio.run(BambooHRAdapter().fetch(FakeSession(), comp, retries=0))

    assert len(jobs) == 2
    assert calls[0][0:2] == ("GET", "https://testcorp.bamboohr.com/careers/list")


def test_bamboohr_fetch_rejects_invalid_slug():
    comp = Company(name="TestCorp", ats="bamboohr", slug="bad/slug", tier=2)
    with pytest.raises(ValueError, match="Invalid BambooHR board slug"):
        asyncio.run(BambooHRAdapter().fetch(None, comp))


def test_breezy_adapter_parses_server_rendered_listing_fixture():
    comp = Company(name="TestCorp", ats="breezy", slug="testcorp", tier=2)
    raw_html = (FIXTURES_DIR / "breezy_sample.html").read_text(encoding="utf-8")

    jobs = BreezyAdapter().parse(raw_html, comp)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.job_id == "breezy:testcorp:abc123-software-engineer-intern"
    assert first.company_key == "breezy:testcorp"
    assert first.title == "Software Engineer Intern"
    assert first.location == "Bengaluru, IN"
    assert first.url == "https://testcorp.breezy.hr/p/abc123-software-engineer-intern"
    assert first.remote is None
    assert first.description == ""
    assert first.posted_at is None
    assert first.salary is None
    assert ADAPTERS["breezy"].ats == "breezy"


def test_breezy_adapter_fetch_uses_public_board_root():
    comp = Company(name="TestCorp", ats="breezy", slug="testcorp", tier=2)
    fixture_html = (FIXTURES_DIR / "breezy_sample.html").read_text(encoding="utf-8")
    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return fixture_html

    class FakeSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

    jobs = asyncio.run(BreezyAdapter().fetch(FakeSession(), comp, retries=0))

    assert len(jobs) == 2
    assert calls[0][0:2] == ("GET", "https://testcorp.breezy.hr/")


def test_breezy_fetch_rejects_invalid_slug():
    comp = Company(name="TestCorp", ats="breezy", slug="bad/slug", tier=2)
    with pytest.raises(ValueError, match="Invalid Breezy board slug"):
        asyncio.run(BreezyAdapter().fetch(None, comp))


def test_jsonld_adapter_handles_graph_relative_urls_and_malformed_entries():
    comp = Company(
        name="TestCorp",
        ats="jsonld",
        slug="testcorp",
        tier=1,
        extra="https://example.com/careers",
    )
    raw_html = """
    <script type="application/ld+json">not json</script>
    <script type="application/ld+json; charset=utf-8">
    {
      "@graph": [
        {"@type": "Organization", "name": "TestCorp"},
        {
          "@type": "https://schema.org/JobPosting",
          "title": "Backend Intern",
          "url": "/jobs/backend-intern",
          "description": "<p>Build <strong>reliable</strong> services.</p>",
          "jobLocation": [
            {"address": {"addressLocality": "Pune", "addressRegion": "Maharashtra", "addressCountry": "India"}},
            {"address": {"addressLocality": "Pune", "addressRegion": "Maharashtra", "addressCountry": "India"}}
          ]
        },
        {"@type": "JobPosting", "title": " "}
      ]
    }
    </script>
    """

    jobs = JsonLdAdapter().parse(raw_html, comp)

    assert len(jobs) == 1
    assert jobs[0].url == "https://example.com/jobs/backend-intern"
    assert jobs[0].job_id == "jsonld:testcorp:519520db4a5b"
    assert jobs[0].description == "Build reliable services."
    assert jobs[0].location == "Pune, Maharashtra, India"
    assert jobs[0].salary is None


def test_jsonld_adapter_fetch_uses_configured_url_and_shared_fetcher():
    comp = Company(
        name="TestCorp",
        ats="jsonld",
        slug="testcorp",
        tier=1,
        extra="https://example.com/careers",
    )
    fixture_html = (FIXTURES_DIR / "jsonld_sample.html").read_text(encoding="utf-8")
    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return fixture_html

    class FakeSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

    jobs = asyncio.run(JsonLdAdapter().fetch(FakeSession(), comp, retries=0))

    assert len(jobs) == 1
    assert calls[0][0:2] == ("GET", comp.extra)
    assert calls[0][2]["timeout"].total == 15.0


def test_jsonld_fetch_requires_absolute_url(sample_company):
    comp = sample_company("jsonld", "testcorp")
    with pytest.raises(ValueError, match="absolute page URL"):
        asyncio.run(JsonLdAdapter().fetch(None, comp))


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, NotFoundError), (403, FetchError)],
)
def test_jsonld_fetch_surfaces_http_errors(status, error):
    comp = Company(
        name="TestCorp",
        ats="jsonld",
        slug="testcorp",
        tier=1,
        extra="https://example.com/careers",
    )

    class FakeResponse:
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return "request failed"

    class FakeSession:
        def request(self, *_args, **_kwargs):
            response = FakeResponse()
            response.status = status
            return response

    with pytest.raises(error):
        asyncio.run(JsonLdAdapter().fetch(FakeSession(), comp, retries=0))


def test_jsonld_page_without_postings_logs_once(caplog):
    comp = Company(
        name="TestCorp",
        ats="jsonld",
        slug="testcorp",
        tier=1,
        extra="https://example.com/careers",
    )

    with caplog.at_level("WARNING"):
        jobs = JsonLdAdapter().parse(
            '<script type="application/ld+json">not json</script>',
            comp,
        )

    assert jobs == []
    assert sum("No JobPosting JSON-LD found" in record.message for record in caplog.records) == 1


def test_registry_with_extra_column(tmp_path):
    csv_file = tmp_path / "companies.csv"
    csv_file.write_text(
        "name,ats,slug,tier,extra\n"
        "NVIDIA,workday,nvidia,1,https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs\n"
        "Delivery Hero,smartrecruiters,deliveryhero,2,\n"
        "Fortanix,workable,fortanix,2,\n"
        "AnantaX Technologies,jsonld,anantax,2,https://www.anantaxtechnologies.com/jobs/reactjs-developer-intern-in-rajkot\n"
        "TestCorp,recruitee,testcorp,2,\n"
        "TestCorp,bamboohr,testcorp,2,\n"
        "TestCorp,breezy,testcorp,2,\n",
        encoding="utf-8",
    )
    comps = load_companies(csv_file, allow_extra=True)
    assert len(comps) == 7
    assert comps[0].ats == "workday"
    assert comps[0].extra == "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
    assert comps[1].ats == "smartrecruiters"
    assert comps[1].extra is None
    assert comps[2].ats == "workable"
    assert comps[3].ats == "jsonld"
    assert comps[4].ats == "recruitee"
    assert comps[5].ats == "bamboohr"
    assert comps[6].ats == "breezy"
    assert comps[3].extra == "https://www.anantaxtechnologies.com/jobs/reactjs-developer-intern-in-rajkot"
