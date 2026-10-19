"""Phase 10: alert ledger, repeat suppression, dismissed list, and new-only digest."""
import sqlite3
import pytest
from src.filters import FilterResult
from src.models import Company, Job
from src.notify import build_digest_email
from src.registry import load_dismissed
from src.store import Store, job_fingerprint

MATCH = FilterResult(True, country="India", min_exp=0.0, exp_signal="title_entry")
NOW = "2026-10-20T04:00:00Z"


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def job(company: Company, native_id: str, title: str = "SDE Intern", location: str = "Bengaluru, India") -> Job:
    return Job(
        job_id=f"{company.ats}:{company.slug}:{native_id}",
        company_key=company.key,
        company=company.name,
        ats=company.ats,
        title=title,
        location=location,
        url=f"https://example.com/{company.slug}/{native_id}",
        description="",
        posted_at=None,
        salary=None,
        remote=None,
    )


def seed(store: Store, company: Company) -> None:
    """First crawl seeds silently; later crawls produce alerts."""
    store.sync_companies([company])
    store.apply_crawl(company, [(job(company, "seed", "Accountant"), FilterResult(False))], "2026-10-01T00:00:00Z")


def crawl(store: Store, company: Company, jobs: list[Job], now: str) -> None:
    seed_job = job(company, "seed", "Accountant")
    store.apply_crawl(company, [(seed_job, FilterResult(False))] + [(j, MATCH) for j in jobs], now)


def send_alerts(store: Store, now: str, **kwargs) -> list[str]:
    store.suppress_repeat_alerts(now, **kwargs)
    pending = store.pending_alerts(100)
    store.mark_alerted([r["job_id"] for r in pending], now)
    return [r["job_id"] for r in pending]


@pytest.mark.parametrize(
    "a, b",
    [
        (("Acme Pvt Ltd", "SDE Intern - Pune (Summer 2027)", "Pune, India"), ("Acme", "SDE Intern - Bengaluru", "Bengaluru")),
        (("Acme", "Software Engineering Intern (2027 Start)", "Remote"), ("Acme", "Software Engineering Intern", "Hyderabad")),
        (("Acme", "[Backend, Onsite] SWE Intern - 6 Months", "Bengaluru, Onsite"), ("Acme", "Backend SWE Intern", "Bengaluru")),
    ],
)
def test_fingerprint_collapses_reposts(a, b):
    assert job_fingerprint(*a) == job_fingerprint(*b)


def test_fingerprint_keeps_different_openings_apart():
    assert job_fingerprint("Acme", "SDE Intern - Backend", "Pune") != job_fingerprint("Acme", "SDE Intern - Frontend", "Pune")
    assert job_fingerprint("Acme", "SDE Intern", "Pune") != job_fingerprint("Beta", "SDE Intern", "Pune")


def test_repost_with_new_job_id_is_not_alerted_again(store):
    acme = Company("Acme", "greenhouse", "acme", 2)
    seed(store, acme)
    crawl(store, acme, [job(acme, "1", "SDE Intern (Summer 2027)")], "2026-10-02T00:00:00Z")
    assert send_alerts(store, "2026-10-02T00:00:00Z") == ["greenhouse:acme:1"]

    # The posting closes, then is reposted with a new ID and a new city.
    crawl(store, acme, [], "2026-10-03T00:00:00Z")
    crawl(store, acme, [], "2026-10-04T00:00:00Z")
    crawl(store, acme, [job(acme, "2", "SDE Intern - Pune", "Pune, India")], "2026-10-05T00:00:00Z")
    assert send_alerts(store, "2026-10-05T00:00:00Z") == []
    assert store.pending_alerts(100) == []


def test_same_opening_on_another_ats_board_later_is_not_alerted(store):
    gh = Company("Acme", "greenhouse", "acme", 2)
    lever = Company("Acme", "lever", "acme", 2)
    seed(store, gh)
    seed(store, lever)
    crawl(store, gh, [job(gh, "1")], "2026-10-02T00:00:00Z")
    assert send_alerts(store, "2026-10-02T00:00:00Z") == ["greenhouse:acme:1"]
    crawl(store, gh, [], "2026-10-03T00:00:00Z")
    crawl(store, gh, [], "2026-10-04T00:00:00Z")
    crawl(store, lever, [job(lever, "x", "SDE Intern", "Remote - India")], "2026-10-05T00:00:00Z")
    assert send_alerts(store, "2026-10-05T00:00:00Z") == []


def test_repost_after_suppression_window_alerts_again(store):
    acme = Company("Acme", "greenhouse", "acme", 2)
    seed(store, acme)
    crawl(store, acme, [job(acme, "1")], "2026-01-01T00:00:00Z")
    send_alerts(store, "2026-01-01T00:00:00Z", window_days=120)
    crawl(store, acme, [job(acme, "2")], "2026-06-01T00:00:00Z")
    assert send_alerts(store, "2026-06-01T00:00:00Z", window_days=120) == ["greenhouse:acme:2"]


def test_dismissed_url_and_job_id_are_never_alerted(store):
    acme = Company("Acme", "greenhouse", "acme", 2)
    seed(store, acme)
    crawl(store, acme, [job(acme, "1", "SDE Intern"), job(acme, "2", "ML Intern"), job(acme, "3", "Data Intern")], NOW)
    dismissed = {"https://example.com/acme/1", "greenhouse:acme:2"}
    assert send_alerts(store, NOW, dismissed=dismissed) == ["greenhouse:acme:3"]


def test_digest_lists_only_matches_never_sent(store):
    acme = Company("Acme", "greenhouse", "acme", 2)
    new_board = Company("Newco", "ashby", "newco", 3)
    seed(store, acme)
    crawl(store, acme, [job(acme, "1")], "2026-10-02T00:00:00Z")
    send_alerts(store, "2026-10-02T00:00:00Z")

    # A newly merged board's first crawl is silent, so its matches were never emailed.
    store.sync_companies([new_board])
    store.apply_crawl(new_board, [(job(new_board, "a", "Backend Intern"), MATCH)], "2026-10-03T00:00:00Z")
    assert store.pending_alerts(100) == []

    digest = store.digest_candidates(NOW)
    assert [r["job_id"] for r in digest] == ["ashby:newco:a"]
    store.mark_alerted([r["job_id"] for r in digest], NOW)
    assert store.digest_candidates(NOW) == []


def test_digest_skips_dismissed(store):
    newco = Company("Newco", "ashby", "newco", 3)
    store.sync_companies([newco])
    store.apply_crawl(newco, [(job(newco, "a"), MATCH)], NOW)
    assert store.digest_candidates(NOW, dismissed={"ashby:newco:a"}) == []


def test_existing_alerted_matches_are_backfilled_into_ledger(tmp_path):
    db = tmp_path / "jobs.db"
    acme = Company("Acme", "greenhouse", "acme", 2)
    s = Store(str(db))
    seed(s, acme)
    crawl(s, acme, [job(acme, "1")], "2026-10-02T00:00:00Z")
    s.conn.execute("UPDATE jobs SET alerted = 1")
    # Simulate a database written before the ledger existed.
    s.conn.execute("DELETE FROM alert_log")
    s.conn.execute("DELETE FROM meta WHERE key = 'alert_log_backfilled'")
    s.conn.execute("UPDATE jobs SET fingerprint = NULL")
    s.conn.commit()
    s.close()

    s = Store(str(db))
    assert s.conn.execute("SELECT job_id FROM alert_log").fetchall()[0]["job_id"] == "greenhouse:acme:1"
    assert s.digest_candidates(NOW) == []
    crawl(s, acme, [job(acme, "1"), job(acme, "9", "SDE Intern - Pune", "Pune")], NOW)
    assert send_alerts(s, NOW) == []
    s.close()


def _rows(entries):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE j (job_id, company, title, location, min_exp, max_exp, posted_at, url, description)")
    conn.executemany("INSERT INTO j VALUES (?, ?, ?, ?, 0.0, NULL, NULL, ?, '')", entries)
    return conn.execute("SELECT * FROM j").fetchall()


def test_build_digest_email_lists_new_and_counts_earlier():
    rows = _rows([("a", "Acme", "<script>x</script> Intern", "Pune", "https://e.com/a")])
    subject, text, html_body = build_digest_email(rows, open_matches=10, now_utc=NOW)
    assert subject == "[JobRadar] Daily digest: 1 new, 10 open matches"
    assert "9 earlier match(es) are still open" in text
    assert "<script>" not in html_body and "&lt;script&gt;" in html_body


def test_build_digest_email_without_new_rows():
    subject, text, html_body = build_digest_email([], open_matches=9, now_utc=NOW)
    assert subject == "[JobRadar] Daily digest: 0 new, 9 open matches"
    assert "No new matches" in text and "9 earlier" in text


def test_load_dismissed(tmp_path):
    path = tmp_path / "dismissed.txt"
    path.write_text("# comment\n\nhttps://e.com/job/1/\ngreenhouse:acme:2\nhttps://e.com/x#frag\n")
    assert load_dismissed(path) == {"https://e.com/job/1", "greenhouse:acme:2", "https://e.com/x#frag"}
    assert load_dismissed(tmp_path / "missing.txt") == set()
