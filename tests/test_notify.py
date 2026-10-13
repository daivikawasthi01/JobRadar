"""Tests for src/notify.py pure functions."""
import sqlite3
from src.notify import build_email, format_exp, utc_to_ist_str


def make_row(title: str, company: str, location: str, min_exp: float | None, max_exp: float | None, posted_at: str, url: str) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE t (
            title TEXT, company TEXT, location TEXT, min_exp REAL, max_exp REAL, posted_at TEXT, url TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, company, location, min_exp, max_exp, posted_at, url),
    )
    row = cur.execute("SELECT * FROM t").fetchone()
    conn.close()
    return row


def test_build_email_subject_and_table():
    r1 = make_row("Associate SWE", "Google", "Bengaluru, India", 0.0, 2.0, "2026-10-12T04:30:00Z", "https://google.com/1")
    r2 = make_row("Backend Engineer", "Microsoft", "Hyderabad, India", 1.0, None, "2026-10-12T05:00:00Z", "https://ms.com/2")
    r3 = make_row("Fullstack Developer", "Meta", "Pune, India", None, None, "2026-10-12T06:00:00Z", "https://meta.com/3")

    subject, text, html_body = build_email([r1, r2, r3], "2026-10-12T07:00:00Z")

    assert subject == "[New Job] 3 new matches: Google, Microsoft, Meta"
    assert "Google" in text
    assert "Microsoft" in text
    assert "Meta" in text
    assert "0-2" in html_body
    assert "1+" in html_body
    assert "?" in html_body
    assert "Apply" in html_body


def test_build_email_html_escaping():
    malicious_title = "<script>alert('xss')</script> & SWE"
    r = make_row(malicious_title, "EvilCorp & Co", "Pune <India>", 0.0, None, "2026-10-12T04:30:00Z", "https://example.com/evil")

    subject, text, html_body = build_email([r], "2026-10-12T05:00:00Z")

    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "&lt;/script&gt;" in html_body
    assert "&amp; SWE" in html_body
    assert "EvilCorp &amp; Co" in html_body
    assert "Pune &lt;India&gt;" in html_body


def test_build_email_more_than_3_companies():
    rows = [
        make_row(f"Role {i}", f"Company {i}", "Loc", 0.0, 1.0, "2026-10-12T00:00:00Z", f"https://example.com/{i}")
        for i in range(5)
    ]
    subject, _, _ = build_email(rows, "2026-10-12T01:00:00Z")
    assert subject == "[New Job] 5 new matches: Company 0, Company 1, Company 2…"


def test_format_exp():
    assert format_exp(0.0, 2.0) == "0-2"
    assert format_exp(2.0, None) == "2+"
    assert format_exp(None, None) == "?"


def test_utc_to_ist_str():
    # 04:30 UTC is 10:00 IST
    ist_str = utc_to_ist_str("2026-10-12T04:30:00Z")
    assert "10:00 IST" in ist_str
    assert "12 Oct" in ist_str
