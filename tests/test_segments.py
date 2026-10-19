"""YC India import, company stage metadata, and startup-first polling/ordering."""
import json
from pathlib import Path
import pytest
from src.discovery import load_input_companies
from src.filters import FilterResult
from src.models import Company, Job
from src.notify import build_email, format_stage
from src.registry import (
    CompanyMeta,
    estimate_segment,
    load_company_meta,
    segment_rank,
    upsert_company_meta,
)
from src.store import Store
from src.yc_discovery import company_meta_from_yc, hq_country, select_india_companies, write_inputs

FIXTURE = Path(__file__).parent / "fixtures" / "yc_companies_sample.json"
MATCH = FilterResult(True, country="India", min_exp=0.0, exp_signal="title_entry")


@pytest.fixture
def yc():
    return json.loads(FIXTURE.read_text())


def test_selects_only_active_india_companies(yc):
    names = {c["name"] for c in select_india_companies(yc)}
    assert names == {"Razorpay", "RedCarpetUp", "GoLorry", "Zuddl"}


def test_yc_meta_estimates_stage_from_team_size(yc):
    by_name = {c["name"]: company_meta_from_yc(c) for c in select_india_companies(yc)}
    assert by_name["GoLorry"].segment == "seed"
    assert by_name["RedCarpetUp"].segment == "series_a"
    assert by_name["Razorpay"].segment == "large"
    assert by_name["GoLorry"].team_size == 30
    assert by_name["GoLorry"].source.startswith("yc:")
    assert by_name["Zuddl"].hq_country == "other"
    assert by_name["Razorpay"].hq_country == "India"


@pytest.mark.parametrize(
    "size, segment",
    [(None, "unknown"), (0, "unknown"), (1, "seed"), (30, "seed"), (31, "series_a"), (150, "series_a"),
     (151, "series_b"), (400, "series_b"), (401, "midsize"), (2000, "midsize"), (2001, "large")],
)
def test_estimate_segment_boundaries(size, segment):
    assert estimate_segment(size) == segment


def test_segment_rank_puts_startups_first_and_large_last():
    order = sorted(["large", None, "midsize", "series_b", "seed", "bogus", "series_a"], key=segment_rank)
    assert order[:3] == ["seed", "series_a", "series_b"]
    assert order[-1] == "large"


def test_yc_inputs_are_readable_by_discovery(yc, tmp_path):
    path = tmp_path / "yc_india.csv"
    write_inputs(select_india_companies(yc), path)
    items = load_input_companies([str(path)])
    assert {i["name"] for i in items} == {"Razorpay", "RedCarpetUp", "GoLorry", "Zuddl"}
    assert next(i for i in items if i["name"] == "Razorpay")["website"] == "https://razorpay.com"


def test_upsert_meta_is_idempotent_and_keeps_manual_rows(tmp_path):
    path = tmp_path / "company_meta.csv"
    rows = [CompanyMeta("GoLorry", "seed", 30, "India", "yc:S18"), CompanyMeta("Acme Pvt Ltd", "seed", 10, "India", "yc:W20")]
    assert upsert_company_meta(path, rows) == 2
    assert upsert_company_meta(path, rows) == 0

    text = path.read_text().replace("Acme Pvt Ltd,seed,10,India,yc:W20", "Acme Pvt Ltd,series_b,10,India,manual")
    path.write_text(text)
    assert upsert_company_meta(path, rows) == 0
    meta = load_company_meta(path)
    assert meta["acme"].segment == "series_b"
    assert meta["golorry"].team_size == 30


def test_unknown_segment_in_meta_falls_back(tmp_path):
    path = tmp_path / "company_meta.csv"
    path.write_text("name,segment,team_size,hq_country,source\nAcme,unicorn,,India,manual\n")
    assert load_company_meta(path)["acme"].segment == "unknown"


def _job(company: Company, native_id: str, title: str = "SDE Intern") -> Job:
    return Job(
        job_id=f"{company.ats}:{company.slug}:{native_id}", company_key=company.key, company=company.name,
        ats=company.ats, title=title, location="Bengaluru, India", url=f"https://e.com/{company.slug}/{native_id}",
        description="", posted_at=None, salary=None, remote=None,
    )


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_alerts_are_ordered_startup_first(store):
    big = Company("BigCo", "greenhouse", "bigco", 1)
    seed_co = Company("TinyStartup", "ashby", "tiny", 3)
    meta = {"bigco": CompanyMeta("BigCo", "large", 5000), "tinystartup": CompanyMeta("TinyStartup", "seed", 12)}
    store.sync_companies([big, seed_co], meta)
    for comp in (big, seed_co):
        store.apply_crawl(comp, [(_job(comp, "seed", "Accountant"), FilterResult(False))], "2026-10-01T00:00:00Z")
    store.apply_crawl(seed_co, [(_job(seed_co, "seed", "Accountant"), FilterResult(False)), (_job(seed_co, "1"), MATCH)], "2026-10-02T00:00:00Z")
    store.apply_crawl(big, [(_job(big, "seed", "Accountant"), FilterResult(False)), (_job(big, "1", "ML Intern"), MATCH)], "2026-10-03T00:00:00Z")

    pending = store.pending_alerts(100)
    assert [r["company"] for r in pending] == ["TinyStartup", "BigCo"]
    assert format_stage(pending[0]) == "Seed · 12 ppl"
    _, text, html_body = build_email(pending, "2026-10-03T00:00:00Z")
    assert "[Seed · 12 ppl]" in text
    assert ">Stage</th>" in html_body and "Large · 5000 ppl" in html_body


def test_startup_boards_poll_at_priority_interval(store):
    startup = Company("TinyStartup", "ashby", "tiny", 3)
    plain = Company("Plain", "ashby", "plain", 3)
    store.sync_companies([startup, plain], {"tinystartup": CompanyMeta("TinyStartup", "series_a", 80)})
    for comp in (startup, plain):
        store.apply_crawl(comp, [], "2026-10-01T00:00:00Z")
    rows = {
        r["company_key"]: r["next_check"]
        for r in store.conn.execute("SELECT company_key, next_check FROM companies")
    }
    assert rows["ashby:tiny"] == "2026-10-01T00:15:00Z"
    assert rows["ashby:plain"] == "2026-10-02T00:00:00Z"
    due = store.companies_due(60, 1440, "2026-10-01T00:20:00Z")
    assert [c.key for c in due] == ["ashby:tiny"]


def test_sync_without_meta_keeps_existing_segment(store):
    comp = Company("TinyStartup", "ashby", "tiny", 3)
    store.sync_companies([comp], {"tinystartup": CompanyMeta("TinyStartup", "seed", 5)})
    store.sync_companies([comp])
    assert store.conn.execute("SELECT segment FROM companies").fetchone()[0] == "seed"
    store.sync_companies([comp], {})
    assert store.conn.execute("SELECT segment FROM companies").fetchone()[0] is None
