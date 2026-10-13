"""CLI entry point for JobRadar."""
import argparse
import sys
from src.config import ConfigError, load_config
from src.registry import RegistryError, load_companies


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobradar", description="JobRadar crawler and alert system")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate config.yaml and companies.csv")
    validate_parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    validate_parser.add_argument("--companies", default="config/companies.csv", help="Path to companies.csv")
    validate_parser.set_defaults(func=validate_command)

    # run (Phase 4+)
    run_parser = subparsers.add_parser("run", help="Run crawl cycle")
    run_parser.add_argument("--dry-run", action="store_true", help="Crawl without modifying database or sending alerts")
    run_parser.add_argument("--no-email", action="store_true", help="Skip email notifications")
    run_parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="Crawl only specific tier")
    run_parser.add_argument("--company", help="Crawl only company with this slug")
    run_parser.add_argument("--limit", type=int, help="Limit number of companies to crawl")
    run_parser.set_defaults(func=lambda args: print("run command will be wired in Phase 4") or 0)

    # stats (Phase 4+)
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")
    stats_parser.set_defaults(func=lambda args: print("stats command will be wired in Phase 4") or 0)

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
