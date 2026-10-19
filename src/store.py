"""SQLite store and state management for companies, jobs, and diff lifecycle."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any
import zlib
from src.fetcher import NotFoundError
from src.filters import FilterResult
from src.models import Company, Job
from src.registry import SEGMENTS, STARTUP_SEGMENTS, CompanyMeta
from src.textutil import now_utc_iso

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
  priority_board INTEGER NOT NULL DEFAULT 0,
  next_check TEXT,
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
  canonical_key TEXT,
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

-- One row per job fingerprint that has reached the human (instant alert or digest).
-- Never pruned with closed jobs, so reposts and relistings are not alerted again.
CREATE TABLE IF NOT EXISTS alert_log (
  fingerprint TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  alerted_at TEXT NOT NULL
);
"""


def decompress_description(description: bytes | str) -> str:
    """Read plain-text descriptions and legacy zlib-compressed rows."""
    if isinstance(description, str):
        return description
    try:
        return zlib.decompress(description).decode("utf-8")
    except zlib.error:
        return description.decode("utf-8")


def canonical_job_key(company: str, title: str, location: str) -> str:
    """Normalize company, title, and location for cross-source deduplication."""
    return "|".join(
        (_normalize_company(company), _normalize_words(title), _normalize_words(location))
    )


COMPANY_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "pvt", "private", "corp", "corporation", "co", "company"}
# Words that change between reposts of the same opening and should not make it look new.
FINGERPRINT_NOISE = re.compile(
    r"\b(?:20[2-3]\d|summer|winter|spring|fall|autumn|off[ -]?cycle|onsite|on[ -]?site|"
    r"in[ -]?office|remote|hybrid|wfh|\d+\s*(?:-\s*)?months?|month|start|batch)\b"
)


def _normalize_words(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _normalize_company(company: str) -> str:
    words = _normalize_words(company).split()
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def job_fingerprint(company: str, title: str, location: str) -> str:
    """Identify an opening across reposts, cities, seasons, and ATS boards.

    Years, seasons, durations, work-mode words, and words from the job's own
    location are removed from the title, so "SDE Intern - Pune (Summer 2027)"
    and "SDE Intern - Bengaluru" share a fingerprint at the same company.
    """
    title_n = FINGERPRINT_NOISE.sub(" ", title.casefold())
    title_words = _normalize_words(title_n).split()
    location_words = set(_normalize_words(location or "").split())
    location_words |= {
        "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "mumbai", "delhi",
        "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad", "india", "ncr",
    }
    kept = [w for w in title_words if w not in location_words]
    return f"{_normalize_company(company)}|{' '.join(kept or title_words)}"


# SQL sort key matching registry.segment_rank: seed first, unknown before large.
SEGMENT_RANK_SQL = "CASE COALESCE(c.segment, 'unknown') " + " ".join(
    f"WHEN '{segment}' THEN {rank}" for rank, segment in enumerate(SEGMENTS)
) + f" ELSE {SEGMENTS.index('unknown')} END"
STARTUP_SQL = "c.segment IN (" + ", ".join(f"'{s}'" for s in sorted(STARTUP_SEGMENTS)) + ")"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
            company_columns = {
                row["name"] for row in self.conn.execute("PRAGMA table_info(companies)")
            }
            if "priority_board" not in company_columns:
                self.conn.execute(
                    "ALTER TABLE companies ADD COLUMN priority_board INTEGER NOT NULL DEFAULT 0"
                )
            if "next_check" not in company_columns:
                self.conn.execute("ALTER TABLE companies ADD COLUMN next_check TEXT")
            if "segment" not in company_columns:
                self.conn.execute("ALTER TABLE companies ADD COLUMN segment TEXT")
            if "team_size" not in company_columns:
                self.conn.execute("ALTER TABLE companies ADD COLUMN team_size INTEGER")

            job_columns = {
                row["name"] for row in self.conn.execute("PRAGMA table_info(jobs)")
            }
            if "canonical_key" not in job_columns:
                self.conn.execute("ALTER TABLE jobs ADD COLUMN canonical_key TEXT")
            if "fingerprint" not in job_columns:
                self.conn.execute("ALTER TABLE jobs ADD COLUMN fingerprint TEXT")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_key, status)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint)"
            )
            for row in self.conn.execute(
                "SELECT job_id, company, title, location FROM jobs WHERE fingerprint IS NULL"
            ).fetchall():
                self.conn.execute(
                    "UPDATE jobs SET fingerprint = ? WHERE job_id = ?",
                    (job_fingerprint(row["company"], row["title"], row["location"]), row["job_id"]),
                )
            backfilled = self.conn.execute(
                "SELECT 1 FROM meta WHERE key = 'alert_log_backfilled'"
            ).fetchone()
            if not backfilled:
                # Matches that existed before the ledger were already emailed or shown
                # in a digest; record them so they never come back.
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO alert_log (fingerprint, job_id, company, title, url, alerted_at)
                    SELECT fingerprint, job_id, company, title, url, first_seen
                    FROM jobs WHERE matched = 1 AND alerted = 1
                    ORDER BY first_seen
                    """
                )
                self.conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('alert_log_backfilled', '1')"
                )
            legacy_jobs = self.conn.execute(
                "SELECT job_id, company, title, location FROM jobs WHERE canonical_key IS NULL"
            ).fetchall()
            for row in legacy_jobs:
                self.conn.execute(
                    "UPDATE jobs SET canonical_key = ? WHERE job_id = ?",
                    (
                        canonical_job_key(row["company"], row["title"], row["location"]),
                        row["job_id"],
                    ),
                )
            self.conn.execute(
                """
                UPDATE companies
                SET priority_board = 1
                WHERE EXISTS (
                    SELECT 1 FROM jobs
                    WHERE jobs.company_key = companies.company_key AND jobs.matched = 1
                )
                """
            )
            compressed_rows = self.conn.execute(
                "SELECT job_id, description FROM jobs WHERE typeof(description) = 'blob'"
            ).fetchall()
            for row in compressed_rows:
                self.conn.execute(
                    "UPDATE jobs SET description = ? WHERE job_id = ?",
                    (decompress_description(row["description"]), row["job_id"]),
                )
        if compressed_rows:
            self.conn.execute("VACUUM")

    def close(self) -> None:
        self.conn.close()

    def sync_companies(
        self, companies: list[Company], meta: dict[str, CompanyMeta] | None = None
    ) -> None:
        """Upsert companies from companies.csv without resetting crawl stats.

        When `meta` (from company_meta.csv, keyed by normalized name) is given, each
        company's segment and team size are set from it, or cleared if absent.
        """
        from src.discovery import normalize_company_name

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
                if meta is not None:
                    m = meta.get(normalize_company_name(comp.name))
                    self.conn.execute(
                        "UPDATE companies SET segment = ?, team_size = ? WHERE company_key = ?",
                        (m.segment if m else None, m.team_size if m else None, comp.key),
                    )

    def companies_due(
        self,
        tier2_min_interval_minutes: int,
        tier3_min_interval_minutes: int,
        now: str,
        only_tier: int | None = None,
        only_slug: str | None = None,
        limit: int | None = None,
        tier1_min_interval_minutes: int = 15,
        priority_min_interval_minutes: int = 15,
    ) -> list[Company]:
        """Find companies due for crawling based on their effective tier and intervals."""
        now_dt = _parse_utc(now)
        cutoff_t1 = (now_dt - timedelta(minutes=tier1_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_t2 = (now_dt - timedelta(minutes=tier2_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_t3 = (now_dt - timedelta(minutes=tier3_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_priority = (now_dt - timedelta(minutes=priority_min_interval_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cur = self.conn.cursor()
        query = """
            SELECT company_key, name, ats, slug, tier, auto_tier,
                   COALESCE(auto_tier, tier) AS effective_tier,
                   last_crawled_at, priority_board, next_check,
                   COALESCE({STARTUP}, 0) AS startup
            FROM companies AS c
            WHERE disabled = 0
              AND (
                (next_check IS NOT NULL AND next_check <= ?)
                OR (
                  next_check IS NULL AND (
                    last_crawled_at IS NULL
                    OR ((priority_board = 1 OR {STARTUP}) AND last_crawled_at <= ?)
                    OR (priority_board = 0 AND NOT COALESCE({STARTUP}, 0) AND COALESCE(auto_tier, tier) = 1 AND last_crawled_at <= ?)
                    OR (priority_board = 0 AND NOT COALESCE({STARTUP}, 0) AND COALESCE(auto_tier, tier) = 2 AND last_crawled_at <= ?)
                    OR (priority_board = 0 AND NOT COALESCE({STARTUP}, 0) AND COALESCE(auto_tier, tier) = 3 AND last_crawled_at <= ?)
                  )
                )
              )
            ORDER BY
                priority_board DESC,
                startup DESC,
                COALESCE(auto_tier, tier) ASC,
                CASE WHEN last_crawled_at IS NULL THEN 1 ELSE 0 END ASC,
                last_crawled_at ASC
        """.replace("{STARTUP}", STARTUP_SQL)
        rows = cur.execute(
            query,
            (now, cutoff_priority, cutoff_t1, cutoff_t2, cutoff_t3),
        ).fetchall()

        # If > 800 companies are due, prioritize known matching boards and higher tiers.
        if len(rows) > 800:
            priority_and_tier1_2 = [
                r for r in rows
                if r["priority_board"] == 1 or r["startup"] or r["effective_tier"] in (1, 2)
            ]
            lower_priority = [
                r for r in rows
                if r["priority_board"] != 1 and not r["startup"] and r["effective_tier"] > 2
            ]
            deferred_count = max(0, len(rows) - 800)
            logger.info(
                "More than 800 companies due (%d); deferring %d lower-priority boards",
                len(rows),
                deferred_count,
            )
            rows = (priority_and_tier1_2 + lower_priority)[:800]

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
        tier1_min_interval_minutes: int = 15,
        tier2_min_interval_minutes: int = 60,
        tier3_min_interval_minutes: int = 1440,
        priority_min_interval_minutes: int = 15,
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
                canonical_key = canonical_job_key(job.company, job.title, job.location)
                fingerprint = job_fingerprint(job.company, job.title, job.location)
                duplicate_exists = cur.execute(
                    "SELECT 1 FROM jobs WHERE canonical_key = ? AND ats != ? AND status = 'open' LIMIT 1",
                    (canonical_key, job.ats),
                ).fetchone() is not None

                if job.job_id not in known:
                    # New job
                    alerted_val = 1 if is_first_crawl or duplicate_exists else 0
                    cur.execute(
                        """
                        INSERT INTO jobs (
                            job_id, company_key, company, ats, title, location, country,
                            remote, url, description, posted_at, salary, canonical_key, fingerprint,
                            min_exp, max_exp, exp_signal, matched, reject_reason, first_seen, last_seen,
                            status, closed_at, miss_count, alerted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, 0, ?)
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
                            canonical_key,
                            fingerprint,
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
                    if res.matched and not is_first_crawl and not duplicate_exists:
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
                                description = ?, posted_at = ?, salary = ?, canonical_key = ?, fingerprint = ?, min_exp = ?, max_exp = ?,
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
                                canonical_key,
                                fingerprint,
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
                                description = ?, posted_at = ?, salary = ?, canonical_key = ?, fingerprint = ?, min_exp = ?, max_exp = ?,
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
                                canonical_key,
                                fingerprint,
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
                    next_check = ?,
                    last_error = NULL,
                    consecutive_errors = 0,
                    consecutive_404 = 0,
                    priority_board = CASE WHEN priority_board = 1 OR ? = 1 THEN 1 ELSE 0 END,
                    empty_streak = ?
                WHERE company_key = ?
                """,
                (
                    now,
                    now,
                    self._next_check(
                        now,
                        company.tier,
                        bool(comp_row["priority_board"])
                        or comp_row["segment"] in STARTUP_SEGMENTS
                        or any(res.matched for _, res in jobs_with_results),
                        tier1_min_interval_minutes,
                        tier2_min_interval_minutes,
                        tier3_min_interval_minutes,
                        priority_min_interval_minutes,
                    ),
                    int(any(res.matched for _, res in jobs_with_results)),
                    empty_streak,
                    company.key,
                ),
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

    @staticmethod
    def _next_check(
        now: str,
        tier: int,
        priority: bool,
        tier1_minutes: int,
        tier2_minutes: int,
        tier3_minutes: int,
        priority_minutes: int,
    ) -> str:
        interval = (
            priority_minutes
            if priority
            else tier1_minutes
            if tier == 1
            else tier2_minutes
            if tier == 2
            else tier3_minutes
        )
        return (_parse_utc(now) + timedelta(minutes=interval)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def record_error(
        self,
        company: Company,
        err: Exception,
        now: str,
        disable_after_consecutive_404: int = 5,
        tier1_min_interval_minutes: int = 15,
        tier2_min_interval_minutes: int = 60,
        tier3_min_interval_minutes: int = 1440,
        priority_min_interval_minutes: int = 15,
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
                    next_check = ?,
                    disabled = CASE WHEN ? = 1 THEN 1 ELSE disabled END
                WHERE company_key = ?
                """,
                (
                    err_msg,
                    consec_err,
                    consec_404,
                    self._next_check(
                        now,
                        company.tier,
                        bool(comp_row["priority_board"]) or comp_row["segment"] in STARTUP_SEGMENTS
                        if comp_row else False,
                        tier1_min_interval_minutes,
                        tier2_min_interval_minutes,
                        tier3_min_interval_minutes,
                        priority_min_interval_minutes,
                    ),
                    disabled,
                    company.key,
                ),
            )

    def pending_alerts(self, limit: int = 100) -> list[sqlite3.Row]:
        """Fetch pending job alerts: matched=1, alerted=0, status='open'.

        Ordered startup-first by company segment (seed, Series A, B, ...), then newest first.
        """
        if limit <= 0:
            return []
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT j.*, c.segment, c.team_size FROM jobs AS j
            LEFT JOIN companies AS c USING (company_key)
            WHERE j.matched = 1 AND j.alerted = 0 AND j.status = 'open'
            ORDER BY {SEGMENT_RANK_SQL}, j.first_seen DESC
            LIMIT ?
            """.replace("{SEGMENT_RANK_SQL}", SEGMENT_RANK_SQL),
            (limit,),
        ).fetchall()
        selected: list[sqlite3.Row] = []
        seen_sources: dict[str, set[str]] = {}
        for row in rows:
            key = row["canonical_key"] or canonical_job_key(
                row["company"], row["title"], row["location"]
            )
            sources = seen_sources.setdefault(key, set())
            if any(source != row["ats"] for source in sources):
                continue
            sources.add(row["ats"])
            selected.append(row)
            if len(selected) >= limit:
                break
        return selected

    def mark_alerted(self, job_ids: list[str], now: str | None = None) -> None:
        """Mark given jobs as alerted and record their fingerprints in the alert ledger."""
        if not job_ids:
            return
        now = now or now_utc_iso()
        with self.conn:
            cur = self.conn.cursor()
            for job_id in job_ids:
                row = cur.execute(
                    "SELECT canonical_key, ats, fingerprint, company, title, url FROM jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE jobs SET alerted = 1
                        WHERE canonical_key = ? AND (ats != ? OR job_id = ?)
                        """,
                        (row["canonical_key"], row["ats"], job_id),
                    )
                    if row["fingerprint"]:
                        cur.execute(
                            """
                            INSERT INTO alert_log (fingerprint, job_id, company, title, url, alerted_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(fingerprint) DO UPDATE SET
                              job_id = excluded.job_id, company = excluded.company,
                              title = excluded.title, url = excluded.url,
                              alerted_at = excluded.alerted_at
                            """,
                            (row["fingerprint"], job_id, row["company"], row["title"], row["url"], now),
                        )

    def _recently_alerted(self, now: str, window_days: int) -> set[str]:
        cutoff = (_parse_utc(now) - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            r["fingerprint"]
            for r in self.conn.execute(
                "SELECT fingerprint FROM alert_log WHERE alerted_at >= ?", (cutoff,)
            )
        }

    @staticmethod
    def _is_dismissed(row: sqlite3.Row, dismissed: set[str]) -> bool:
        return bool(dismissed) and any(
            value and value in dismissed
            for value in (row["job_id"], (row["url"] or "").rstrip("/"), row["fingerprint"])
        )

    def suppress_repeat_alerts(
        self, now: str, window_days: int = 120, dismissed: set[str] | None = None
    ) -> int:
        """Mark pending matches as alerted when the human already saw that opening.

        An opening counts as seen when its fingerprint was alerted within
        `window_days`, or when it is listed in the dismissed set (job_id, URL, or
        fingerprint). Returns how many pending jobs were suppressed.
        """
        dismissed = dismissed or set()
        recent = self._recently_alerted(now, window_days)
        rows = self.conn.execute(
            """
            SELECT job_id, url, fingerprint FROM jobs
            WHERE matched = 1 AND alerted = 0 AND status = 'open'
            """
        ).fetchall()
        suppressed = [
            r["job_id"] for r in rows
            if r["fingerprint"] in recent or self._is_dismissed(r, dismissed)
        ]
        if suppressed:
            with self.conn:
                self.conn.executemany(
                    "UPDATE jobs SET alerted = 1 WHERE job_id = ?",
                    [(job_id,) for job_id in suppressed],
                )
        return len(suppressed)

    def digest_candidates(
        self,
        now: str,
        limit: int = 100,
        window_days: int = 120,
        dismissed: set[str] | None = None,
    ) -> list[sqlite3.Row]:
        """Open matches the human has never been sent, e.g. silently seeded boards.

        Anything already in the alert ledger (instant alert or an earlier digest) or
        dismissed is left out, so a digest never repeats a job.
        """
        if limit <= 0:
            return []
        dismissed = dismissed or set()
        recent = self._recently_alerted(now, window_days)
        rows = self.conn.execute(
            """
            SELECT j.*, c.segment, c.team_size FROM jobs AS j
            LEFT JOIN companies AS c USING (company_key)
            WHERE j.matched = 1 AND j.status = 'open'
            ORDER BY {SEGMENT_RANK_SQL}, j.first_seen DESC
            """.replace("{SEGMENT_RANK_SQL}", SEGMENT_RANK_SQL)
        ).fetchall()
        selected: list[sqlite3.Row] = []
        seen_sources: dict[str, set[str]] = {}
        for row in rows:
            if row["fingerprint"] in recent or self._is_dismissed(row, dismissed):
                continue
            sources = seen_sources.setdefault(row["canonical_key"], set())
            if any(source != row["ats"] for source in sources):
                continue
            sources.add(row["ats"])
            selected.append(row)
            if len(selected) >= limit:
                break
        return selected

    def prune_closed_jobs(self, now: str, retention_days: int = 45) -> int:
        """Prune long-closed jobs and compact the database."""
        if retention_days < 0:
            raise ValueError("retention_days must be non-negative")
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        cutoff = (now_dt - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM jobs WHERE status = 'closed' AND closed_at < ?",
                (cutoff,),
            )
        deleted = cursor.rowcount
        self.conn.execute("VACUUM")
        return deleted

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
