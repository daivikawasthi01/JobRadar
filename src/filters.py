"""Filter models and evaluation logic for JobRadar."""
from dataclasses import dataclass


@dataclass
class FilterResult:
    matched: bool
    reject_reason: str | None = None  # e.g. "title_excluded", "role_not_included", "experience_too_high", "country_not_allowed"
    country: str | None = None
    min_exp: float | None = None
    max_exp: float | None = None
    exp_signal: str = "unknown"  # "fresher_keyword" | "range" | "plus" | "at_least" | "plain" | "up_to" | "title_entry" | "unknown"
