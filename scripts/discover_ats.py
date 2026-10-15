#!/usr/bin/env python3
"""Probe seeded company names against public ATS boards."""
import argparse
import asyncio
import logging
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.discovery import run_discovery


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        help="Optional company names/CSV input; defaults to seed_company_names*.txt and config/inputs/",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=2.0,
        help="Maximum global request rate (default 2; hard-capped at 5)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge the reviewed candidate CSV into config/companies.csv",
    )
    args = parser.parse_args(argv)
    if args.rps <= 0:
        parser.error("--rps must be greater than zero")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    return asyncio.run(run_discovery(args))


if __name__ == "__main__":
    raise SystemExit(main())
