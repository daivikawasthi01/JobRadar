"""CLI entry point and crawl orchestrator for JobRadar."""
import argparse
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
import aiohttp
from src.adapters import ADAPTERS
from src.config import Config, ConfigError, load_config
from src.discovery import run_discovery
from src.export import export_excel
from src.filters import evaluate
from src.hn_discovery import HNDiscoveryError, run_hn_discovery
from src.yc_discovery import YCDiscoveryError, run_yc_discovery
from src.models import Company, Job
from src.notify import (
    IST,
    build_digest_email,
    build_email,
    load_env_file,
    send_email,
    send_ntfy,
)
from src.registry import RegistryError, load_companies, load_company_meta, load_dismissed
from src.store import Store
from src.textutil import now_utc_iso

logger = logging.getLogger("jobradar")
CRAWL_FETCH_BUDGET_SECONDS = 7 * 60


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def validate_command(args: argparse.Namespace) -> int:
    """Validate config.yaml and companies.csv."""
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected config error: {exc}", file=sys.stderr)
        return 2

    try:
        companies = load_companies(args.companies)
    except RegistryError as exc:
        print(f"Companies error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected companies error: {exc}", file=sys.stderr)
        return 2

    print(f"config ok, companies: {len(companies)}")
    return 0


def stats_command(args: argparse.Namespace) -> int:
    """Print store database statistics."""
    db_path = Path("data/jobs.db")
    if not db_path.exists():
        print("Database not found at data/jobs.db (run a crawl first)")
        return 0

    store = Store(str(db_path))
    st = store.stats()
    print(f"Companies total: {st['companies_total']} | disabled: {st['companies_disabled']} | errored: {st['companies_errored']}")
    print(f"Jobs total:      {st['jobs_total']} | open: {st['jobs_open']} | matched open: {st['jobs_matched_open']}")
    print(f"Pending alerts:  {st['pending_alerts']}")
    store.close()
    return 0


def test_email_command(args: argparse.Namespace) -> int:
    """Send a dummy 2-row test alert email."""
    setup_logging()
    load_env_file()

    # Create dummy in-memory rows to build realistic email
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE dummy_jobs (
            job_id TEXT, company TEXT, title TEXT, location TEXT,
            min_exp REAL, max_exp REAL, posted_at TEXT, url TEXT, description TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO dummy_jobs VALUES
        ('test:1', 'Acme Corp', 'SDE Intern', 'Bengaluru, India', 0.0, NULL, '2026-10-12T04:30:00Z', 'https://example.com/job/1', 'Eligible for the 2027 batch.'),
        ('test:2', 'Beta Labs', 'Backend Engineer Intern', 'Pune, India', 0.0, NULL, '2026-10-12T05:00:00Z', 'https://example.com/job/2', 'Graduation batch year not specified.')
        """
    )
    rows = conn.execute("SELECT * FROM dummy_jobs").fetchall()

    now = now_utc_iso()
    subject, text, html_body = build_email(rows, now)

    try:
        send_email(subject, text, html_body)
        alert_to = os.environ.get("ALERT_TO", "recipient")
        print(f"Test email successfully sent to {alert_to}")
        return 0
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Failed to send test email: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def hn_discovery_command(args: argparse.Namespace) -> int:
    """Extract company names from the latest HN hiring thread."""
    setup_logging()
    try:
        output_path, count = asyncio.run(run_hn_discovery(args.output_dir))
    except HNDiscoveryError as exc:
        print(f"HN discovery error: {exc}", file=sys.stderr)
        return 1
    print(f"Extracted {count} company name(s) to {output_path}. Run `python scripts/discover_ats.py` to probe ATS boards.")
    return 0


def yc_discovery_command(args: argparse.Namespace) -> int:
    """Refresh India-region YC companies as discovery input plus stage metadata."""
    setup_logging()
    try:
        count, written = asyncio.run(run_yc_discovery(args.output, args.meta))
    except YCDiscoveryError as exc:
        print(f"YC discovery error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wrote {count} YC India companies to {args.output}; {written} metadata row(s) "
        f"added or updated in {args.meta}. Run `python -m src.main discover` next."
    )
    return 0


async def fetch_due_companies(
    session: aiohttp.ClientSession,
    companies: list[Company],
    cfg: Config,
    budget_seconds: float,
) -> tuple[dict[Company, list[Job] | Exception], list[Company]]:
    """Fetch due boards concurrently and cancel unfinished work at the run deadline."""
    semaphore = asyncio.Semaphore(cfg.polling.concurrency)
    tasks: dict[asyncio.Task, Company] = {}
    skipped: list[Company] = []
    results: dict[Company, list[Job] | Exception] = {}

    for company in companies:
        adapter = ADAPTERS.get(company.ats)
        if adapter is None:
            logger.warning("No adapter found for ATS '%s' (company %s)", company.ats, company.key)
            skipped.append(company)
            continue
        task = asyncio.create_task(
            adapter.fetch(
                session,
                company,
                timeout_seconds=cfg.polling.timeout_seconds,
                retries=cfg.polling.retries,
                semaphore=semaphore,
            )
        )
        tasks[task] = company

    pending = set(tasks)
    deadline = asyncio.get_running_loop().time() + max(0.0, budget_seconds)
    while pending:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        completed, pending = await asyncio.wait(
            pending,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not completed:
            break
        for task in completed:
            try:
                results[tasks[task]] = task.result()
            except Exception as exc:
                results[tasks[task]] = exc

    if pending:
        timed_out = [tasks[task] for task in pending]
        skipped.extend(timed_out)
        for company in timed_out:
            logger.warning(
                "Crawl time budget reached; skipped board %s (%s), leaving it due for a later run.",
                company.name,
                company.key,
            )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    return results, skipped


async def run_crawl(args: argparse.Namespace) -> int:
    """Execute a single crawl cycle."""
    setup_logging()
    load_env_file()
    t0 = time.perf_counter()

    # Step 1: Load config and companies
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected config error: {exc}", file=sys.stderr)
        return 2

    try:
        companies = load_companies(args.companies)
    except RegistryError as exc:
        print(f"Companies error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected companies error: {exc}", file=sys.stderr)
        return 2

    # Database setup: dry-run keeps changes entirely in-memory
    db_file = Path("data/jobs.db")
    if args.dry_run:
        store = Store(":memory:")
        if db_file.exists():
            with sqlite3.connect(str(db_file)) as disk_conn:
                disk_conn.backup(store.conn)
    else:
        store = Store(str(db_file))

    store.sync_companies(companies, load_company_meta(args.company_meta))

    # Step 2: Determine due companies
    now = now_utc_iso()
    due = store.companies_due(
        tier2_min_interval_minutes=cfg.polling.tier2_min_interval_minutes,
        tier3_min_interval_minutes=cfg.polling.tier3_min_interval_minutes,
        now=now,
        only_tier=args.tier,
        only_slug=args.company,
        limit=args.limit,
        tier1_min_interval_minutes=cfg.polling.tier1_min_interval_minutes,
        priority_min_interval_minutes=cfg.polling.priority_min_interval_minutes,
    )

    # Step 3: Fetch due boards concurrently, stopping before the workflow deadline.
    headers = {"User-Agent": cfg.polling.user_agent}
    skipped_companies: list[Company] = []
    async with aiohttp.ClientSession(headers=headers) as session:
        fetch_results, skipped_companies = await fetch_due_companies(
            session,
            due,
            cfg,
            budget_seconds=CRAWL_FETCH_BUDGET_SECONDS - (time.perf_counter() - t0),
        )

    # Step 4: Process crawl results and update store
    ok_count = 0
    error_count = 0
    jobs_seen = 0
    total_new = 0
    total_new_matched = 0
    total_closed = 0

    for comp in due:
        if comp not in fetch_results:
            continue
        res = fetch_results[comp]
        if isinstance(res, Exception):
            logger.warning("Crawl failed for %s (%s): %s", comp.name, comp.key, res)
            store.record_error(
                comp,
                res,
                now,
                disable_after_consecutive_404=cfg.limits.disable_after_consecutive_404,
                tier1_min_interval_minutes=cfg.polling.tier1_min_interval_minutes,
                tier2_min_interval_minutes=cfg.polling.tier2_min_interval_minutes,
                tier3_min_interval_minutes=cfg.polling.tier3_min_interval_minutes,
                priority_min_interval_minutes=cfg.polling.priority_min_interval_minutes,
            )
            error_count += 1
        else:
            ok_count += 1
            fetched_jobs: list[Job] = res
            jobs_seen += len(fetched_jobs)

            jobs_with_results = [
                (job, evaluate(job, cfg.filters)) for job in fetched_jobs
            ]

            diff = store.apply_crawl(
                comp,
                jobs_with_results,
                now,
                empty_streak_before_close=cfg.limits.empty_streak_before_close,
                close_after_missed_cycles=cfg.limits.close_after_missed_cycles,
                tier1_min_interval_minutes=cfg.polling.tier1_min_interval_minutes,
                tier2_min_interval_minutes=cfg.polling.tier2_min_interval_minutes,
                tier3_min_interval_minutes=cfg.polling.tier3_min_interval_minutes,
                priority_min_interval_minutes=cfg.polling.priority_min_interval_minutes,
            )

            total_new += len(diff.new)
            total_new_matched += len(diff.new_matched)
            total_closed += len(diff.closed)

            if args.dry_run and diff.new:
                for j, r in jobs_with_results:
                    if j.job_id in diff.new:
                        logger.info(
                            "[dry-run new] %s | %s | %s | matched=%s (%s)",
                            comp.name,
                            j.title,
                            j.location or "no loc",
                            r.matched,
                            r.reject_reason or "ok",
                        )

    if not args.dry_run:
        pruned_jobs = store.prune_closed_jobs(now, retention_days=45)
        if pruned_jobs:
            logger.info("Pruned %d jobs closed for more than 45 days.", pruned_jobs)

    # Step 5: Excel export
    if not args.dry_run:
        try:
            export_excel(store, cfg.export.excel_path)
        except Exception as e:
            logger.warning("Excel export failed: %s", e)

    # Step 6: Email notifications
    emails_sent = 0
    dismissed = load_dismissed(cfg.alerts.dismissed_path)
    if not args.dry_run and not args.no_email and cfg.alerts.email_enabled:
        suppressed = store.suppress_repeat_alerts(
            now, cfg.alerts.repeat_suppression_days, dismissed
        )
        if suppressed:
            logger.info("Suppressed %d pending match(es) already sent or dismissed.", suppressed)
        pending = store.pending_alerts(limit=cfg.alerts.max_jobs_per_email)
        if pending:
            subject, text, html_body = build_email(pending, now)
            try:
                send_email(subject, text, html_body)
                store.mark_alerted([r["job_id"] for r in pending], now)
                emails_sent = 1
                if cfg.alerts.ntfy_topic:
                    send_ntfy(cfg.alerts.ntfy_topic, subject, f"{len(pending)} new jobs matched")
            except Exception as e:
                logger.warning("Failed to send alert email: %s", e)

    # Step 7: Daily digest
    if not args.dry_run and not args.no_email and cfg.alerts.email_enabled:
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        now_ist = now_dt.astimezone(IST)
        today_ist = now_ist.strftime("%Y-%m-%d")
        last_digest = store.get_meta("last_digest_date")

        if now_ist.hour >= cfg.alerts.daily_digest_hour_ist and last_digest != today_ist:
            cur = store.conn.cursor()
            matched_open = cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE matched = 1 AND status = 'open'"
            ).fetchone()[0]
            digest_rows = store.digest_candidates(
                now,
                limit=cfg.alerts.max_jobs_per_email,
                window_days=cfg.alerts.repeat_suppression_days,
                dismissed=dismissed,
            )
            digest_subject, digest_text, digest_html = build_digest_email(
                digest_rows, matched_open, now
            )

            excel_path = Path(cfg.export.excel_path)
            attachments = []
            if excel_path.exists():
                with open(excel_path, "rb") as f:
                    attachments.append(("jobs.xlsx", f.read()))

            try:
                send_email(digest_subject, digest_text, digest_html, attachments=attachments)
                store.mark_alerted([r["job_id"] for r in digest_rows], now)
                store.set_meta("last_digest_date", today_ist)
                logger.info("Daily digest sent with jobs.xlsx attached.")
            except Exception as e:
                logger.warning("Failed to send daily digest: %s", e)

    store.close()
    elapsed = round(time.perf_counter() - t0, 1)

    # Step 8: Print single summary line
    print(
        f"run ok | companies={len(due)} ok={ok_count} errors={error_count} skipped={len(skipped_companies)} | "
        f"jobs_seen={jobs_seen} new={total_new} new_matched={total_new_matched} closed={total_closed} | "
        f"emails={emails_sent} | secs={elapsed}"
    )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobradar", description="JobRadar crawler and alert system")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate config.yaml and companies.csv")
    validate_parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    validate_parser.add_argument("--companies", default="config/companies.csv", help="Path to companies.csv")
    validate_parser.set_defaults(func=validate_command)

    # run
    run_parser = subparsers.add_parser("run", help="Run crawl cycle")
    run_parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    run_parser.add_argument("--companies", default="config/companies.csv", help="Path to companies.csv")
    run_parser.add_argument("--dry-run", action="store_true", help="Crawl without modifying database or sending alerts")
    run_parser.add_argument("--no-email", action="store_true", help="Skip email notifications")
    run_parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="Crawl only specific tier")
    run_parser.add_argument("--company", help="Crawl only company with this slug")
    run_parser.add_argument("--limit", type=int, help="Limit number of companies to crawl")
    run_parser.add_argument("--company-meta", default="config/company_meta.csv", help="Path to company_meta.csv")
    run_parser.set_defaults(func=lambda args: asyncio.run(run_crawl(args)))

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")
    stats_parser.set_defaults(func=stats_command)

    # discover
    discover_parser = subparsers.add_parser("discover", help="Discover company ATS slugs")
    discover_parser.add_argument("--input", action="append", help="Input company file(s)")
    discover_parser.add_argument("--rps", type=float, default=2.0, help="Requests per second limit")
    discover_parser.add_argument("--merge", action="store_true", help="Merge discovered candidates into companies.csv")
    discover_parser.set_defaults(func=lambda args: asyncio.run(run_discovery(args)))

    # discover-hn
    hn_parser = subparsers.add_parser(
        "discover-hn",
        help="Extract company names from the latest monthly HN hiring thread",
    )
    hn_parser.add_argument(
        "--output-dir",
        default="config/inputs",
        help="Directory for the dated names file consumed by `discover`",
    )
    hn_parser.set_defaults(func=hn_discovery_command)

    # discover-yc
    yc_parser = subparsers.add_parser(
        "discover-yc",
        help="Import India-region YC companies as discovery input with stage metadata",
    )
    yc_parser.add_argument("--output", default="config/inputs/yc_india.csv", help="Discovery input CSV to write")
    yc_parser.add_argument("--meta", default="config/company_meta.csv", help="Company metadata CSV to update")
    yc_parser.set_defaults(func=yc_discovery_command)

    # test-email
    test_email_parser = subparsers.add_parser("test-email", help="Send a test alert email")
    test_email_parser.set_defaults(func=test_email_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
