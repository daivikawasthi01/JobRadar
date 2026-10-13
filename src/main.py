"""CLI entry point and crawl orchestrator for JobRadar."""
import argparse
import asyncio
import logging
from pathlib import Path
import sqlite3
import sys
import time
import aiohttp
from src.adapters import ADAPTERS
from src.config import ConfigError, load_config
from src.filters import evaluate
from src.models import Company, Job
from src.registry import RegistryError, load_companies
from src.store import Store
from src.textutil import now_utc_iso

logger = logging.getLogger("jobradar")


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


async def run_crawl(args: argparse.Namespace) -> int:
    """Execute a single crawl cycle."""
    setup_logging()
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

    store.sync_companies(companies)

    # Step 2: Determine due companies
    now = now_utc_iso()
    due = store.companies_due(
        tier2_min_interval_minutes=cfg.polling.tier2_min_interval_minutes,
        tier3_min_interval_minutes=cfg.polling.tier3_min_interval_minutes,
        now=now,
        only_tier=args.tier,
        only_slug=args.company,
        limit=args.limit,
    )

    # Step 3: Fetch due companies concurrently
    semaphore = asyncio.Semaphore(cfg.polling.concurrency)
    headers = {"User-Agent": cfg.polling.user_agent}

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for comp in due:
            adapter = ADAPTERS.get(comp.ats)
            if not adapter:
                logger.warning("No adapter found for ATS '%s' (company %s)", comp.ats, comp.key)
                continue
            tasks.append(
                adapter.fetch(
                    session,
                    comp,
                    timeout_seconds=cfg.polling.timeout_seconds,
                    retries=cfg.polling.retries,
                    semaphore=semaphore,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Step 4: Process crawl results and update store
    ok_count = 0
    error_count = 0
    jobs_seen = 0
    total_new = 0
    total_new_matched = 0
    total_closed = 0

    for comp, res in zip(due, results):
        if isinstance(res, Exception):
            logger.warning("Crawl failed for %s (%s): %s", comp.name, comp.key, res)
            store.record_error(
                comp,
                res,
                now,
                disable_after_consecutive_404=cfg.limits.disable_after_consecutive_404,
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

    # Steps 5, 6, 7 (Excel export, email alerts, digest) will be wired in Phase 5
    emails_sent = 0

    store.close()
    elapsed = round(time.perf_counter() - t0, 1)

    # Step 8: Print single summary line
    print(
        f"run ok | companies={len(due)} ok={ok_count} errors={error_count} | "
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
    run_parser.set_defaults(func=lambda args: asyncio.run(run_crawl(args)))

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")
    stats_parser.set_defaults(func=stats_command)

    # discover (Phase 7)
    discover_parser = subparsers.add_parser("discover", help="Discover company ATS slugs")
    discover_parser.add_argument("--input", action="append", help="Input company file(s)")
    discover_parser.add_argument("--rps", type=float, default=2.0, help="Requests per second limit")
    discover_parser.add_argument("--merge", action="store_true", help="Merge discovered candidates into companies.csv")
    discover_parser.set_defaults(func=lambda args: print("discover command will be wired in Phase 7") or 0)

    # test-email (Phase 5)
    test_email_parser = subparsers.add_parser("test-email", help="Send a test alert email")
    test_email_parser.set_defaults(func=lambda args: print("test-email command will be wired in Phase 5") or 0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
