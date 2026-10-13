"""Company registry loader and validator for JobRadar."""
import csv
import logging
from pathlib import Path
from src.models import Company

logger = logging.getLogger(__name__)

VALID_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "workday"}
VALID_TIERS = {1, 2, 3}


class RegistryError(Exception):
    """Raised when the company CSV is malformed or invalid."""
    pass


def load_companies(
    path: str | Path = "config/companies.csv",
    allow_extra: bool = True,
) -> list[Company]:
    """Load and validate company list from CSV.

    Rules:
    - Header: name,ats,slug,tier (optional 'extra' column allowed from Phase 8 onward).
    - Lines starting with '#' or blank lines are ignored.
    - ats must be one of: greenhouse, lever, ashby, smartrecruiters, workable, workday.
    - tier must be one of: 1, 2, 3.
    - Duplicate (ats, slug) pairs keep the first and log a warning.
    """
    p = Path(path)
    if not p.exists():
        raise RegistryError(f"Company file not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Filter comments and blank lines
    filtered_lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        filtered_lines.append(line)

    if not filtered_lines:
        raise RegistryError(f"Company CSV file {p} is empty or contains only comments")

    reader = csv.reader(filtered_lines)
    try:
        header = next(reader)
    except StopIteration:
        raise RegistryError(f"Company CSV file {p} has no header")

    clean_header = [col.strip().lower() for col in header]

    if not allow_extra:
        if clean_header != ["name", "ats", "slug", "tier"]:
            raise RegistryError(
                f"Invalid CSV header in {p}. Expected exactly 'name,ats,slug,tier', got: {','.join(clean_header)}"
            )
    else:
        if clean_header not in [["name", "ats", "slug", "tier"], ["name", "ats", "slug", "tier", "extra"]]:
            raise RegistryError(
                f"Invalid CSV header in {p}. Expected 'name,ats,slug,tier' or 'name,ats,slug,tier,extra', got: {','.join(clean_header)}"
            )

    companies: list[Company] = []
    seen_keys: set[str] = set()

    for row_idx, row in enumerate(reader, start=2):
        if not row:
            continue

        if len(row) < 4:
            raise RegistryError(
                f"Row {row_idx} in {p} has {len(row)} columns, expected at least 4: {row}"
            )
        if not allow_extra and len(row) > 4:
            raise RegistryError(
                f"Row {row_idx} in {p} has {len(row)} columns, expected exactly 4: {row}"
            )

        name = row[0].strip()
        ats = row[1].strip().lower()
        slug = row[2].strip()
        tier_str = row[3].strip()
        extra = row[4].strip() if len(row) > 4 and row[4].strip() else None

        if not name:
            raise RegistryError(f"Row {row_idx} in {p} has empty company name")
        if ats not in VALID_ATS:
            raise RegistryError(
                f"Row {row_idx} in {p} has invalid ATS '{ats}'. Must be one of: {sorted(VALID_ATS)}"
            )
        if not slug:
            raise RegistryError(f"Row {row_idx} in {p} has empty slug")

        try:
            tier = int(tier_str)
        except ValueError:
            raise RegistryError(
                f"Row {row_idx} in {p} has non-integer tier '{tier_str}'"
            )

        if tier not in VALID_TIERS:
            raise RegistryError(
                f"Row {row_idx} in {p} has invalid tier {tier}. Must be 1, 2, or 3"
            )

        comp = Company(name=name, ats=ats, slug=slug, tier=tier, extra=extra)
        if comp.key in seen_keys:
            logger.warning("Duplicate company key '%s' found at row %d; skipping duplicate", comp.key, row_idx)
            continue

        seen_keys.add(comp.key)
        companies.append(comp)

    return companies
