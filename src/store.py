"""SQLite store and state management for companies, jobs, and diff lifecycle."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any
from src.fetcher import NotFoundError
from src.filters import FilterResult
from src.models import Company, Job

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS companies (
  company_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ats TEXT NOT NULL,
  slug TEXT NOT NULL,
  tier INTEGER NOT NULL,          -- base tier from companies.csv
  auto_tier INTEGER,              -- NULL normally; 2 when a Tier 3 company has an open matched job
  first_crawled_at TEXT,          -- NULL until first successful crawl
  last_crawled_at TEXT,
  last_error TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  consecutive_404 INTEGER NOT NULL DEFAULT 0,
  empty_streak INTEGER NOT NULL DEFAULT 0,
  disabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  company_key TEXT NOT NULL,
  company TEXT NOT NULL,
  ats TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  country TEXT,
  remote INTEGER,
  url TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  posted_at TEXT,
  salary TEXT,
  min_exp REAL,
  max_exp REAL,
  exp_signal TEXT,
  matched INTEGER NOT NULL DEFAULT 0,
  reject_reason TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
  closed_at TEXT,
  miss_count INTEGER NOT NULL DEFAULT 0,
  alerted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_key, status);
CREATE INDEX IF NOT EXISTS idx_jobs_matched ON jobs(matched, status, first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_alert ON jobs(matched, alerted);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


@dataclass
class CrawlDiff:
    new: list[str] = field(default_factory=list)
    new_matched: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)


class Store:
    def __init__(self, path: str = "data/jobs.db"):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    def sync_companies(self, companies: list[Company]) -> None:
        """Upsert companies from companies.csv without resetting crawl stats."""
        with self.conn:
            for comp in companies:
                self.conn.execute(
                    """
                    INSERT INTO companies (company_key, name, ats, slug, tier)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(company_key) DO UPDATE SET
                      name = excluded.name,
                      ats = excluded.ats,
                      slug = excluded.slug,
                      tier = excluded.tier
                    """,
                    (comp.key, comp.name, comp.ats, comp.slug, comp.tier),
                )

    def companies_due(
        self,
        tier2_min_interval_minutes: int,
        tier3_min_interval_minutes: int,
        now: str,
        only_tier: int | None = None,
        only_slug: str | None = None,
        limit: int | None = None,
    ) -> list[Company]:
        """Find companies due for crawling based on their effective tier and intervals."""
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        cutoff_t2 = (now_dt - timedelta(minutes=tier2_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_t3 = (now_dt - timedelta(minutes=tier3_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cur = self.conn.cursor()
        query = """
            SELECT company_key, name, ats, slug, tier, auto_tier,
                   COALESCE(auto_tier, tier) AS effective_tier,
                   last_crawled_at
            FROM companies
            WHERE disabled = 0
              AND (
                COALESCE(auto_tier, tier) = 1
                OR last_crawled_at IS NULL
                OR (COALESCE(auto_tier, tier) = 2 AND last_crawled_at <= ?)
                OR (COALESCE(auto_tier, tier) = 3 AND last_crawled_at <= ?)
              )
            ORDER BY
              COALESCE(auto_tier, tier) ASC,
              CASE WHEN last_crawled_at IS NULL THEN 1 ELSE 0 END ASC,
              last_crawled_at ASC
        """
        rows = cur.execute(query, (cutoff_t2, cutoff_t3)).fetchall()

        # If > 800 companies due, prioritize Tier 1 and Tier 2, defer the rest
        if len(rows) > 800:
            tier1_2 = [r for r in rows if r["effective_tier"] in (1, 2)]
            tier3 = [r for r in rows if r["effective_tier"] > 2]
            deferred_count = max(0, len(rows) - 800)
            logger.info("More than 800 companies due (%d); deferring %d Tier 3 companies", len(rows), deferred_count)
            rows = (tier1_2 + tier3)[:800]

        filtered_companies: list[Company] = []
        for r in rows:
            eff_tier = r["effective_tier"]
            if only_tier is not None and eff_tier != only_tier:
                continue
            if only_slug is not None and r["slug"] != only_slug:
                continue
            filtered_companies.append(
                Company(name=r["name"], ats=r["ats"], slug=r["slug"], tier=r["tier"])
            )
            if limit is not None and len(filtered_companies) >= limit:
                break

        return filtered_companies

    def apply_crawl(
        self,
        company: Company,
        jobs_with_results: list[tuple[Job, FilterResult]],
        now: str,
        empty_streak_before_close: int = 3,
        close_after_missed_cycles: int = 2,
    ) -> CrawlDiff:
        """Apply crawl results in a single transaction per company."""
        diff = CrawlDiff()

        with self.conn:
            cur = self.conn.cursor()
            comp_row = cur.execute(
                "SELECT * FROM companies WHERE company_key = ?", (company.key,)
            ).fetchone()

            if not comp_row:
                # Insert company if not present
                cur.execute(
                    "INSERT INTO companies (company_key, name, ats, slug, tier) VALUES (?, ?, ?, ?, ?)",
                    (company.key, company.name, company.ats, company.slug, company.tier),
                )
                comp_row = cur.execute(
                    "SELECT * FROM companies WHERE company_key = ?", (company.key,)
                ).fetchone()

            is_first_crawl = comp_row["first_crawled_at"] is None

            existing_rows = cur.execute(
                "SELECT * FROM jobs WHERE company_key = ?", (company.key,)
            ).fetchall()
            known = {r["job_id"]: r for r in existing_rows}
            seen_ids = {j.job_id for (j, _) in jobs_with_results}

            for job, res in jobs_with_results:
                remote_val = 1 if job.remote is True else (0 if job.remote is False else None)
                matched_val = 1 if res.matched else 0

                if job.job_id not in known:
                    # New job
                    alerted_val = 1 if is_first_crawl else 0
                    cur.execute(
                        """
                        INSERT INTO jobs (
                            job_id, company_key, company, ats, title, location, country,
                            remote, url, description, posted_at, salary, min_exp, max_exp,
                            exp_signal, matched, reject_reason, first_seen, last_seen,
                            status, closed_at, miss_count, alerted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, 0, ?)
                        """,
                        (
                            job.job_id,
                            company.key,
                            job.company,
                            job.ats,
                            job.title,
                            job.location,
                            res.country,
                            remote_val,
                            job.url,
                            job.description,
                            job.posted_at,
                            job.salary,
                            res.min_exp,
                            res.max_exp,
                            res.exp_signal,
                            matched_val,
                            res.reject_reason,
                            now,
                            now,
                            alerted_val,
                        ),
                    )
                    diff.new.append(job.job_id)
                    if res.matched and not is_first_crawl:
                        diff.new_matched.append(job.job_id)
                else:
                    # Existing job update
                    old = known[job.job_id]
                    if old["status"] == "closed":
                        diff.reopened.append(job.job_id)
                        cur.execute(
                            """
                            UPDATE jobs SET
                                title = ?, location = ?, country = ?, remote = ?, url = ?,
                                description = ?, posted_at = ?, salary = ?, min_exp = ?, max_exp = ?,
                                exp_signal = ?, matched = ?, reject_reason = ?,
                                last_seen = ?, miss_count = 0, status = 'open', closed_at = NULL
                            WHERE job_id = ?
                            """,
                            (
                                job.title,
                                job.location,
                                res.country,
                                remote_val,
                                job.url,
                                job.description,
                                job.posted_at,
                                job.salary,
                                res.min_exp,
                                res.max_exp,
                                res.exp_signal,
                                matched_val,
                                res.reject_reason,
                                now,
                                job.job_id,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE jobs SET
                                title = ?, location = ?, country = ?, remote = ?, url = ?,
                                description = ?, posted_at = ?, salary = ?, min_exp = ?, max_exp = ?,
                                exp_signal = ?, matched = ?, reject_reason = ?,
                                last_seen = ?, miss_count = 0
                            WHERE job_id = ?
                            """,
                            (
                                job.title,
                                job.location,
                                res.country,
                                remote_val,
                                job.url,
                                job.description,
                                job.posted_at,
                                job.salary,
                                res.min_exp,
                                res.max_exp,
                                res.exp_signal,
                                matched_val,
                                res.reject_reason,
                                now,
                                job.job_id,
                            ),
                        )

            open_before = {jid for jid, r in known.items() if r["status"] == "open"}
            missing = open_before - seen_ids

            empty_streak = comp_row["empty_streak"] or 0
            if len(jobs_with_results) == 0 and len(open_before) > 0:
                empty_streak += 1
                if empty_streak >= empty_streak_before_close:
                    for jid in missing:
                        cur.execute(
                            "UPDATE jobs SET status = 'closed', closed_at = ? WHERE job_id = ?",
                            (now, jid),
                        )
                        diff.closed.append(jid)
            else:
                empty_streak = 0
                for jid in missing:
                    miss_count = known[jid]["miss_count"] + 1
                    if miss_count >= close_after_missed_cycles:
                        cur.execute(
                            "UPDATE jobs SET status = 'closed', closed_at = ?, miss_count = ? WHERE job_id = ?",
                            (now, miss_count, jid),
                        )
                        diff.closed.append(jid)
                    else:
                        cur.execute(
                            "UPDATE jobs SET miss_count = ? WHERE job_id = ?",
                            (miss_count, jid),
                        )

            # Update company crawl statistics
            cur.execute(
                """
                UPDATE companies SET
                    first_crawled_at = COALESCE(first_crawled_at, ?),
                    last_crawled_at = ?,
                    last_error = NULL,
                    consecutive_errors = 0,
                    consecutive_404 = 0,
                    empty_streak = ?
                WHERE company_key = ?
                """,
                (now, now, empty_streak, company.key),
            )

            # Auto-tier rule:
            # Count rows with matched=1 AND status='open'.
            # If base tier == 3 and count > 0 -> auto_tier = 2; else NULL.
            if comp_row["tier"] == 3:
                matched_open_count = cur.execute(
                    "SELECT COUNT(*) FROM jobs WHERE company_key = ? AND matched = 1 AND status = 'open'",
                    (company.key,),
                ).fetchone()[0]
                new_auto_tier = 2 if matched_open_count > 0 else None
                cur.execute(
                    "UPDATE companies SET auto_tier = ? WHERE company_key = ?",
                    (new_auto_tier, company.key),
                )

        return diff

    def record_error(
        self,
        company: Company,
        err: Exception,
        now: str,
        disable_after_consecutive_404: int = 5,
    ) -> None:
        """Record a crawl error for a company without touching its jobs."""
        err_msg = str(err)[:300]
        is_404 = isinstance(err, NotFoundError)

        with self.conn:
            cur = self.conn.cursor()
            comp_row = cur.execute(
                "SELECT * FROM companies WHERE company_key = ?", (company.key,)
            ).fetchone()

            if not comp_row:
                cur.execute(
                    "INSERT INTO companies (company_key, name, ats, slug, tier) VALUES (?, ?, ?, ?, ?)",
                    (company.key, company.name, company.ats, company.slug, company.tier),
                )
                consec_err = 0
                consec_404 = 0
            else:
                consec_err = comp_row["consecutive_errors"] or 0
                consec_404 = comp_row["consecutive_404"] or 0

            consec_err += 1
            if is_404:
                consec_404 += 1
                disabled = 1 if consec_404 >= disable_after_consecutive_404 else 0
            else:
                consec_404 = 0
                disabled = 0

            cur.execute(
                """
                UPDATE companies SET
                    last_error = ?,
                    consecutive_errors = ?,
                    consecutive_404 = ?,
                    disabled = CASE WHEN ? = 1 THEN 1 ELSE disabled END
                WHERE company_key = ?
                """,
                (err_msg, consec_err, consec_404, disabled, company.key),
            )

    def pending_alerts(self, limit: int = 100) -> list[sqlite3.Row]:
        """Fetch pending job alerts: matched=1, alerted=0, status='open' ordered newest first."""
        cur = self.conn.cursor()
        return cur.execute(
            """
            SELECT * FROM jobs
            WHERE matched = 1 AND alerted = 0 AND status = 'open'
            ORDER BY first_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def mark_alerted(self, job_ids: list[str]) -> None:
        """Mark given jobs as alerted."""
        if not job_ids:
            return
        with self.conn:
            cur = self.conn.cursor()
            cur.executemany(
                "UPDATE jobs SET alerted = 1 WHERE job_id = ?",
                [(jid,) for jid in job_ids],
            )

    def get_meta(self, key: str) -> str | None:
        """Get value from meta table."""
        cur = self.conn.cursor()
        row = cur.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Set key-value pair in meta table."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def stats(self) -> dict[str, Any]:
        """Return store summary counts."""
        cur = self.conn.cursor()
        total_companies = cur.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        disabled_companies = cur.execute("SELECT COUNT(*) FROM companies WHERE disabled = 1").fetchone()[0]
        errored_companies = cur.execute("SELECT COUNT(*) FROM companies WHERE last_error IS NOT NULL").fetchone()[0]
        total_jobs = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        open_jobs = cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
        matched_jobs = cur.execute("SELECT COUNT(*) FROM jobs WHERE matched = 1").fetchone()[0]
        matched_open_jobs = cur.execute("SELECT COUNT(*) FROM jobs WHERE matched = 1 AND status = 'open'").fetchone()[0]
        pending_alerts_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE matched = 1 AND alerted = 0 AND status = 'open'").fetchone()[0]

        return {
            "companies_total": total_companies,
            "companies_disabled": disabled_companies,
            "companies_errored": errored_companies,
            "jobs_total": total_jobs,
            "jobs_open": open_jobs,
            "jobs_matched": matched_jobs,
            "jobs_matched_open": matched_open_jobs,
            "pending_alerts": pending_alerts_count,
        }
