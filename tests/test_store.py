"""Tests for src/store.py covering all 11 test requirements in BUILD_SPEC.md §B9.4."""
import sqlite3
import pytest
from src.fetcher import FetchError, NotFoundError
from src.filters import FilterResult
from src.models import Company, Job
from src.store import Store, decompress_description


@pytest.fixture
def store():
    # In-memory database for testing
    s = Store(":memory:")
    yield s
    s.close()


def make_job(
    company: Company,
    native_id: str,
    title: str = "Software Engineer",
    matched: bool = True,
) -> tuple[Job, FilterResult]:
    job = Job(
        job_id=f"{company.ats}:{company.slug}:{native_id}",
        company_key=company.key,
        company=company.name,
        ats=company.ats,
        title=title,
        location="Bengaluru, India",
        url=f"https://example.com/jobs/{native_id}",
        description="A great fresher job",
        posted_at="2026-10-12T04:30:00Z",
        salary=None,
        remote=False,
    )
    result = FilterResult(
        matched=matched,
        reject_reason=None if matched else "title_excluded",
        country="India",
        min_exp=0.0,
        max_exp=2.0,
        exp_signal="title_entry",
    )
    return job, result


def test_1_first_crawl_seeds_silently(store):
    """1. First crawl of a company inserts jobs with alerted=1 -> pending_alerts() returns nothing."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    jobs = [make_job(comp, "job-1", matched=True), make_job(comp, "job-2", matched=True)]
    diff = store.apply_crawl(comp, jobs, "2026-10-12T00:00:00Z")

    assert len(diff.new) == 2
    assert len(diff.new_matched) == 0  # Not alerted on first crawl
    pending = store.pending_alerts(100)
    assert len(pending) == 0


def test_2_second_crawl_extra_matched_is_pending(store):
    """2. Second crawl with one extra matched job -> exactly that job is pending."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    # First crawl
    j1 = make_job(comp, "job-1", matched=True)
    store.apply_crawl(comp, [j1], "2026-10-12T00:00:00Z")
    assert len(store.pending_alerts(100)) == 0

    # Second crawl with an extra matched job
    j2 = make_job(comp, "job-2", matched=True)
    diff = store.apply_crawl(comp, [j1, j2], "2026-10-12T00:15:00Z")

    assert diff.new == ["greenhouse:acme:job-2"]
    assert diff.new_matched == ["greenhouse:acme:job-2"]

    pending = store.pending_alerts(100)
    assert len(pending) == 1
    assert pending[0]["job_id"] == "greenhouse:acme:job-2"
    assert pending[0]["alerted"] == 0


def test_3_job_missing_cycles(store):
    """3. A job missing for 1 cycle stays open; missing for 2 cycles -> closed."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    j1 = make_job(comp, "job-1")
    j2 = make_job(comp, "job-2")
    store.apply_crawl(comp, [j1, j2], "2026-10-12T00:00:00Z")

    # Cycle 1 missing j2: only j1 present
    diff1 = store.apply_crawl(comp, [j1], "2026-10-12T00:15:00Z", close_after_missed_cycles=2)
    assert len(diff1.closed) == 0
    cur = store.conn.cursor()
    row = cur.execute("SELECT status, miss_count FROM jobs WHERE job_id = ?", ("greenhouse:acme:job-2",)).fetchone()
    assert row["status"] == "open"
    assert row["miss_count"] == 1

    # Cycle 2 missing j2: only j1 present
    diff2 = store.apply_crawl(comp, [j1], "2026-10-12T00:30:00Z", close_after_missed_cycles=2)
    assert diff2.closed == ["greenhouse:acme:job-2"]
    row = cur.execute("SELECT status, miss_count, closed_at FROM jobs WHERE job_id = ?", ("greenhouse:acme:job-2",)).fetchone()
    assert row["status"] == "closed"
    assert row["closed_at"] == "2026-10-12T00:30:00Z"


def test_4_reopened_job(store):
    """4. A closed job that reappears becomes open, is not pending, and first_seen is unchanged."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    j1 = make_job(comp, "job-1")
    store.apply_crawl(comp, [j1], "2026-10-12T00:00:00Z")

    # Cycle 1 missing j1, Cycle 2 missing j1 -> closes j1
    j_empty_dummy = make_job(comp, "dummy-job")
    store.apply_crawl(comp, [j_empty_dummy], "2026-10-12T00:15:00Z")
    store.apply_crawl(comp, [j_empty_dummy], "2026-10-12T00:30:00Z")

    cur = store.conn.cursor()
    row = cur.execute("SELECT status, first_seen FROM jobs WHERE job_id = ?", ("greenhouse:acme:job-1",)).fetchone()
    assert row["status"] == "closed"
    first_seen_orig = row["first_seen"]

    # Now j1 reappears
    diff = store.apply_crawl(comp, [j1, j_empty_dummy], "2026-10-12T00:45:00Z")
    assert "greenhouse:acme:job-1" in diff.reopened
    assert "greenhouse:acme:job-1" not in diff.new
    assert "greenhouse:acme:job-1" not in diff.new_matched

    # Not pending alert
    pending = store.pending_alerts(100)
    assert not any(p["job_id"] == "greenhouse:acme:job-1" for p in pending)

    # Status is open, closed_at is NULL, first_seen unchanged
    row = cur.execute("SELECT status, closed_at, first_seen FROM jobs WHERE job_id = ?", ("greenhouse:acme:job-1",)).fetchone()
    assert row["status"] == "open"
    assert row["closed_at"] is None
    assert row["first_seen"] == first_seen_orig


def test_5_empty_board_streak_handling(store):
    """5. A fetch returning 0 jobs when 5 were open does not close them on 1st and 2nd, closes on 3rd."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    five_jobs = [make_job(comp, f"j-{i}") for i in range(5)]
    store.apply_crawl(comp, five_jobs, "2026-10-12T00:00:00Z")

    # 1st empty crawl
    diff1 = store.apply_crawl(comp, [], "2026-10-12T00:15:00Z", empty_streak_before_close=3)
    assert len(diff1.closed) == 0
    cur = store.conn.cursor()
    open_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
    assert open_count == 5

    # 2nd empty crawl
    diff2 = store.apply_crawl(comp, [], "2026-10-12T00:30:00Z", empty_streak_before_close=3)
    assert len(diff2.closed) == 0
    open_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
    assert open_count == 5

    # 3rd empty crawl -> all close
    diff3 = store.apply_crawl(comp, [], "2026-10-12T00:45:00Z", empty_streak_before_close=3)
    assert len(diff3.closed) == 5
    open_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
    assert open_count == 0


def test_6_record_error_does_not_close_jobs(store):
    """6. record_error never changes any job's status."""
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])

    j1 = make_job(comp, "j-1")
    store.apply_crawl(comp, [j1], "2026-10-12T00:00:00Z")

    store.record_error(comp, FetchError("Connection timeout"), "2026-10-12T00:15:00Z")
    store.record_error(comp, FetchError("500 Internal Server Error"), "2026-10-12T00:30:00Z")

    cur = store.conn.cursor()
    row = cur.execute("SELECT status FROM jobs WHERE job_id = ?", ("greenhouse:acme:j-1",)).fetchone()
    assert row["status"] == "open"

    comp_row = cur.execute("SELECT consecutive_errors, last_error FROM companies WHERE company_key = ?", (comp.key,)).fetchone()
    assert comp_row["consecutive_errors"] == 2
    assert "500 Internal" in comp_row["last_error"]


def test_7_five_consecutive_404_disables_company(store):
    """7. Five consecutive NotFoundError -> disabled=1."""
    comp = Company(name="GhostCorp", ats="lever", slug="ghost", tier=2)
    store.sync_companies([comp])

    for i in range(1, 5):
        store.record_error(comp, NotFoundError("Not Found 404"), f"2026-10-12T0{i}:00:00Z")
        row = store.conn.execute("SELECT disabled, consecutive_404 FROM companies WHERE company_key = ?", (comp.key,)).fetchone()
        assert row["disabled"] == 0
        assert row["consecutive_404"] == i

    # 5th 404
    store.record_error(comp, NotFoundError("Not Found 404"), "2026-10-12T05:00:00Z")
    row = store.conn.execute("SELECT disabled, consecutive_404 FROM companies WHERE company_key = ?", (comp.key,)).fetchone()
    assert row["disabled"] == 1
    assert row["consecutive_404"] == 5


def test_8_companies_due_tier1_tier2(store):
    """8. Tier 1 is due every 15m; tier 2 every configured hourly interval."""
    c1 = Company(name="Tier1Comp", ats="greenhouse", slug="c1", tier=1)
    c2_never = Company(name="Tier2Never", ats="greenhouse", slug="c2_never", tier=2)
    c2_recent = Company(name="Tier2Recent", ats="greenhouse", slug="c2_recent", tier=2)
    c2_old = Company(name="Tier2Old", ats="greenhouse", slug="c2_old", tier=2)

    store.sync_companies([c1, c2_never, c2_recent, c2_old])

    now = "2026-10-12T12:00:00Z"
    # c1 crawled 5 min ago
    store.conn.execute("UPDATE companies SET last_crawled_at = '2026-10-12T11:55:00Z' WHERE slug = 'c1'")
    # c2_recent crawled 10 min ago
    store.conn.execute("UPDATE companies SET last_crawled_at = '2026-10-12T11:50:00Z' WHERE slug = 'c2_recent'")
    # c2_old crawled 60 min ago
    store.conn.execute("UPDATE companies SET last_crawled_at = '2026-10-12T11:00:00Z' WHERE slug = 'c2_old'")

    due = store.companies_due(
        tier2_min_interval_minutes=60,
        tier3_min_interval_minutes=1440,
        now=now,
    )
    due_slugs = {c.slug for c in due}

    assert "c1" not in due_slugs
    assert "c2_never" in due_slugs
    assert "c2_old" in due_slugs
    assert "c2_recent" not in due_slugs

    tier1_due = store.companies_due(
        tier2_min_interval_minutes=60,
        tier3_min_interval_minutes=1440,
        now=now,
        tier1_min_interval_minutes=5,
    )
    assert "c1" in {company.slug for company in tier1_due}


def test_9_companies_due_tier3(store):
    """9. Tier 3 is daily: excluded if crawled 2 hours ago, due after 24 hours or if never crawled."""
    c3_never = Company(name="T3Never", ats="ashby", slug="t3_never", tier=3)
    c3_recent = Company(name="T3Recent", ats="ashby", slug="t3_recent", tier=3)
    c3_old = Company(name="T3Old", ats="ashby", slug="t3_old", tier=3)

    store.sync_companies([c3_never, c3_recent, c3_old])

    now = "2026-10-12T12:00:00Z"
    # c3_recent crawled 2 hours (120m) ago
    store.conn.execute("UPDATE companies SET last_crawled_at = '2026-10-12T10:00:00Z' WHERE slug = 't3_recent'")
    # c3_old crawled 25 hours ago
    store.conn.execute("UPDATE companies SET last_crawled_at = '2026-10-11T11:00:00Z' WHERE slug = 't3_old'")

    due = store.companies_due(
        tier2_min_interval_minutes=60,
        tier3_min_interval_minutes=1440,
        now=now,
    )
    due_slugs = {c.slug for c in due}

    assert "t3_never" in due_slugs
    assert "t3_old" in due_slugs
    assert "t3_recent" not in due_slugs


def test_10_tier3_auto_tier_promotion_and_reversion(store):
    """10. A matched Tier 3 board becomes priority; auto_tier reverts when no matches remain open."""
    comp = Company(name="Tier3Dynamic", ats="ashby", slug="t3_dyn", tier=3)
    store.sync_companies([comp])

    now = "2026-10-12T12:00:00Z"

    # Initially has no matched jobs
    row = store.conn.execute("SELECT auto_tier FROM companies WHERE slug = 't3_dyn'").fetchone()
    assert row["auto_tier"] is None

    # Crawl returns 1 matched job
    j1 = make_job(comp, "j-matched", matched=True)
    store.apply_crawl(comp, [j1], now)

    row = store.conn.execute("SELECT auto_tier FROM companies WHERE slug = 't3_dyn'").fetchone()
    assert row["auto_tier"] == 2

    # The matched board is priority and next due 15 minutes after its successful crawl.
    now_15m_later = "2026-10-12T12:15:00Z"
    due = store.companies_due(
        tier2_min_interval_minutes=60,
        tier3_min_interval_minutes=1440,
        now=now_15m_later,
    )
    assert any(c.slug == "t3_dyn" for c in due)

    # Job closes (missing for 2 cycles)
    j_dummy = make_job(comp, "dummy", matched=False)
    store.apply_crawl(comp, [j_dummy], "2026-10-12T13:15:00Z")
    store.apply_crawl(comp, [j_dummy], "2026-10-12T13:30:00Z")

    row = store.conn.execute("SELECT auto_tier FROM companies WHERE slug = 't3_dyn'").fetchone()
    assert row["auto_tier"] is None


def test_11_company_with_zero_jobs(store):
    """11. A company with 0 jobs is stored and stays enabled (not an error, never deleted)."""
    comp = Company(name="QuietCorp", ats="lever", slug="quiet", tier=2)
    store.sync_companies([comp])

    diff = store.apply_crawl(comp, [], "2026-10-12T00:00:00Z")
    assert len(diff.new) == 0
    assert len(diff.closed) == 0

    comp_row = store.conn.execute("SELECT disabled, last_crawled_at, last_error FROM companies WHERE slug = 'quiet'").fetchone()
    assert comp_row["disabled"] == 0
    assert comp_row["last_crawled_at"] == "2026-10-12T00:00:00Z"
    assert comp_row["last_error"] is None


def test_next_check_schedule_and_matched_board_promotion(store):
    tier1 = Company(name="Tier One", ats="greenhouse", slug="tier-one", tier=1)
    tier2 = Company(name="Tier Two", ats="lever", slug="tier-two", tier=2)
    tier3 = Company(name="Tier Three", ats="ashby", slug="tier-three", tier=3)
    store.sync_companies([tier1, tier2, tier3])
    now = "2026-10-15T12:00:00Z"

    store.apply_crawl(tier1, [], now)
    store.apply_crawl(tier2, [], now)
    store.apply_crawl(tier3, [], now)
    checks = {
        row["company_key"]: row["next_check"]
        for row in store.conn.execute(
            "SELECT company_key, next_check FROM companies WHERE company_key IN (?, ?, ?)",
            (tier1.key, tier2.key, tier3.key),
        )
    }
    assert checks == {
        tier1.key: "2026-10-15T12:15:00Z",
        tier2.key: "2026-10-15T13:00:00Z",
        tier3.key: "2026-10-16T12:00:00Z",
    }

    store.apply_crawl(
        tier3,
        [make_job(tier3, "matched", matched=True)],
        "2026-10-15T12:01:00Z",
    )
    row = store.conn.execute(
        "SELECT priority_board, next_check FROM companies WHERE company_key = ?",
        (tier3.key,),
    ).fetchone()
    assert row["priority_board"] == 1
    assert row["next_check"] == "2026-10-15T12:16:00Z"

    due_15_minutes = store.companies_due(
        tier2_min_interval_minutes=60,
        tier3_min_interval_minutes=1440,
        now="2026-10-15T12:16:00Z",
    )
    assert tier3.slug in {company.slug for company in due_15_minutes}


def test_record_error_sets_next_check_without_closing_jobs(store):
    company = Company(name="Tier Two", ats="lever", slug="tier-two-error", tier=2)
    store.sync_companies([company])
    store.record_error(
        company,
        FetchError("temporary failure"),
        "2026-10-15T12:00:00Z",
    )
    row = store.conn.execute(
        "SELECT next_check FROM companies WHERE company_key = ?",
        (company.key,),
    ).fetchone()
    assert row["next_check"] == "2026-10-15T13:00:00Z"

    store.conn.execute(
        "UPDATE companies SET priority_board = 1 WHERE company_key = ?",
        (company.key,),
    )
    store.record_error(
        company,
        FetchError("temporary failure"),
        "2026-10-15T13:00:00Z",
    )
    row = store.conn.execute(
        "SELECT next_check FROM companies WHERE company_key = ?",
        (company.key,),
    ).fetchone()
    assert row["next_check"] == "2026-10-15T13:15:00Z"


def test_cross_source_duplicate_alerts_are_deduplicated_but_rows_are_kept(store):
    greenhouse = Company(name="Example Inc.", ats="greenhouse", slug="example", tier=1)
    lever = Company(name="Example", ats="lever", slug="example", tier=1)
    store.sync_companies([greenhouse, lever])

    seed, seed_result = make_job(greenhouse, "seed", matched=False)
    store.apply_crawl(
        greenhouse,
        [(seed, seed_result)],
        "2026-10-15T00:00:00Z",
    )
    original, _ = make_job(greenhouse, "job-1", matched=True)
    store.apply_crawl(
        greenhouse,
        [
            (seed, seed_result),
            (
                original,
                FilterResult(True, country="India", min_exp=0, exp_signal="title_entry"),
            ),
        ],
        "2026-10-15T00:15:00Z",
    )
    duplicate = Job(
        job_id="lever:example:job-2",
        company_key=lever.key,
        company=lever.name,
        ats=lever.ats,
        title="Software Engineer, Intern",
        location="Bengaluru India",
        url="https://example.com/other-source",
        description="",
        posted_at=None,
        salary=None,
        remote=None,
    )
    diff = store.apply_crawl(
        lever,
        [(duplicate, FilterResult(True, country="India", min_exp=0, exp_signal="title_entry"))],
        "2026-10-15T00:16:00Z",
    )

    assert diff.new == ["lever:example:job-2"]
    assert diff.new_matched == []
    assert store.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3
    pending = store.pending_alerts()
    assert len(pending) == 1
    assert pending[0]["job_id"] == original.job_id

    store.mark_alerted([pending[0]["job_id"]])
    assert store.pending_alerts() == []
    assert store.conn.execute("SELECT COUNT(*) FROM jobs WHERE alerted = 1").fetchone()[0] == 3


def test_same_source_jobs_are_not_deduplicated(store):
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])
    seed, _ = make_job(comp, "seed", matched=False)
    store.apply_crawl(comp, [(seed, FilterResult(False))], "2026-10-15T00:00:00Z")

    first, _ = make_job(comp, "first", matched=True)
    second, _ = make_job(comp, "second", matched=True)
    second.title = "software engineer"
    second.location = "Bengaluru India"
    first_result = FilterResult(True, country="India", min_exp=0, exp_signal="title_entry")
    second_result = FilterResult(True, country="India", min_exp=0, exp_signal="title_entry")
    store.apply_crawl(
        comp,
        [(seed, FilterResult(False)), (first, first_result), (second, second_result)],
        "2026-10-15T00:15:00Z",
    )
    assert len(store.pending_alerts()) == 2


def test_descriptions_are_stored_as_plain_text(store):
    description_column = next(
        column
        for column in store.conn.execute("PRAGMA table_info(jobs)")
        if column["name"] == "description"
    )
    assert description_column["type"].upper() == "TEXT"

    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])
    description = "A fresher job description. " * 100
    job, result = make_job(comp, "plain-text")
    job.description = description

    store.apply_crawl(comp, [(job, result)], "2026-10-12T00:00:00Z")

    row = store.conn.execute(
        "SELECT description, typeof(description) AS storage_type FROM jobs WHERE job_id = ?",
        (job.job_id,),
    ).fetchone()
    assert row["storage_type"] == "text"
    assert row["description"] == description


def test_existing_zlib_descriptions_are_migrated_to_plain_text(tmp_path):
    import zlib

    db_path = tmp_path / "compressed.db"
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    description = "Legacy compressed description " * 20

    first_store = Store(str(db_path))
    first_store.sync_companies([comp])
    job, result = make_job(comp, "compressed-legacy")
    job.description = description
    first_store.apply_crawl(comp, [(job, result)], "2026-10-12T00:00:00Z")
    with first_store.conn:
        first_store.conn.execute(
            "UPDATE jobs SET description = ? WHERE job_id = ?",
            (zlib.compress(description.encode("utf-8")), job.job_id),
        )
    first_store.close()

    migrated_store = Store(str(db_path))
    row = migrated_store.conn.execute(
        "SELECT description, typeof(description) AS storage_type FROM jobs WHERE job_id = ?",
        (job.job_id,),
    ).fetchone()
    assert row["storage_type"] == "text"
    assert row["description"] == description
    assert decompress_description(row["description"]) == description
    migrated_store.close()


def test_prune_closed_jobs_keeps_recent_and_open_jobs(store):
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])
    jobs = [make_job(comp, f"prune-{i}") for i in range(3)]
    store.apply_crawl(comp, jobs, "2026-10-15T00:00:00Z")
    store.conn.executemany(
        "UPDATE jobs SET status = ?, closed_at = ? WHERE job_id = ?",
        [
            ("closed", "2026-08-14T00:00:00Z", jobs[0][0].job_id),
            ("closed", "2026-09-01T00:00:00Z", jobs[1][0].job_id),
            ("open", "2026-08-01T00:00:00Z", jobs[2][0].job_id),
        ],
    )

    deleted = store.prune_closed_jobs("2026-10-15T00:00:00Z", retention_days=45)

    assert deleted == 1
    remaining = {
        row["job_id"]
        for row in store.conn.execute("SELECT job_id FROM jobs")
    }
    assert jobs[0][0].job_id not in remaining
    assert jobs[1][0].job_id in remaining
    assert jobs[2][0].job_id in remaining


def test_prune_closed_jobs_defaults_to_45_day_retention(store):
    comp = Company(name="Acme", ats="greenhouse", slug="acme", tier=1)
    store.sync_companies([comp])
    jobs = [make_job(comp, f"prune-default-{i}") for i in range(2)]
    store.apply_crawl(comp, jobs, "2026-10-15T00:00:00Z")
    store.conn.executemany(
        "UPDATE jobs SET status = 'closed', closed_at = ? WHERE job_id = ?",
        [
            ("2026-08-30T00:00:00Z", jobs[0][0].job_id),
            ("2026-09-01T00:00:00Z", jobs[1][0].job_id),
        ],
    )

    assert store.prune_closed_jobs("2026-10-15T00:00:00Z") == 1
