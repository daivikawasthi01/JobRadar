"""Configuration loader and schema definition for JobRadar."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""
    pass


@dataclass
class FilterConfig:
    roles_include: list[str] = field(default_factory=lambda: [
        "associate software engineer",
        "associate engineer",
        "associate developer",
        "software engineer",
        "software developer",
        "software development engineer",
        "sde",
        "full stack",
        "fullstack",
        "full-stack",
        "backend engineer",
        "back-end engineer",
        "back end engineer",
        "backend developer",
        "frontend engineer",
        "front-end engineer",
        "frontend developer",
        "ai engineer",
        "ml engineer",
        "machine learning engineer",
        "data engineer",
        "python developer",
        "graduate engineer trainee",
        "engineer trainee",
        "trainee",
        "new grad",
        "junior",
    ])
    roles_exclude_title: list[str] = field(default_factory=lambda: [
        "senior",
        "sr",
        "lead",
        "principal",
        "staff",
        "manager",
        "director",
        "head",
        "architect",
        "vp",
        "intern",
    ])
    entry_level_title_tokens: list[str] = field(default_factory=lambda: [
        "associate",
        "junior",
        "jr",
        "trainee",
        "graduate",
        "new grad",
        "entry level",
        "sde-1",
        "sde 1",
        "sde1",
    ])
    max_min_experience: float = 2.0
    keep_unknown_experience: bool = True
    countries: list[str] = field(default_factory=lambda: ["India"])
    include_remote_unspecified: bool = False
    target_grad_years: list[int] = field(default_factory=list)
    allow_unspecified_grad_year: bool = True


@dataclass
class PollingConfig:
    tier2_min_interval_minutes: int = 55
    tier3_min_interval_minutes: int = 235
    concurrency: int = 30
    timeout_seconds: int = 15
    retries: int = 3
    user_agent: str = "JobRadar/1.0 (personal job search)"


@dataclass
class AlertsConfig:
    email_enabled: bool = True
    max_jobs_per_email: int = 100
    daily_digest_hour_ist: int = 8
    ntfy_topic: str = ""


@dataclass
class ExportConfig:
    excel_path: str = "data/jobs.xlsx"


@dataclass
class LimitsConfig:
    disable_after_consecutive_404: int = 5
    close_after_missed_cycles: int = 2
    empty_streak_before_close: int = 3


@dataclass
class Config:
    filters: FilterConfig = field(default_factory=FilterConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)


def _merge_dict(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overrides over defaults."""
    res = dict(defaults)
    for k, v in overrides.items():
        if k in res and isinstance(res[k], dict) and isinstance(v, dict):
            res[k] = _merge_dict(res[k], v)
        else:
            res[k] = v
    return res


def load_config(path: str | Path = "config/config.yaml") -> Config:
    """Load configuration from a YAML file, merging with built-in defaults."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML syntax in {p}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to read {p}: {exc}") from exc

    if data is None:
        data = {}
    elif not isinstance(data, dict):
        raise ConfigError(f"Expected mapping at root of {p}, got {type(data).__name__}")

    filters_raw = data.get("filters", {})
    polling_raw = data.get("polling", {})
    alerts_raw = data.get("alerts", {})
    export_raw = data.get("export", {})
    limits_raw = data.get("limits", {})

    def_filter = FilterConfig()
    filter_cfg = FilterConfig(
        roles_include=filters_raw.get("roles_include", def_filter.roles_include),
        roles_exclude_title=filters_raw.get("roles_exclude_title", def_filter.roles_exclude_title),
        entry_level_title_tokens=filters_raw.get("entry_level_title_tokens", def_filter.entry_level_title_tokens),
        max_min_experience=float(filters_raw.get("max_min_experience", def_filter.max_min_experience)),
        keep_unknown_experience=bool(filters_raw.get("keep_unknown_experience", def_filter.keep_unknown_experience)),
        countries=filters_raw.get("countries", def_filter.countries),
        include_remote_unspecified=bool(filters_raw.get("include_remote_unspecified", def_filter.include_remote_unspecified)),
        target_grad_years=[int(y) for y in filters_raw.get("target_grad_years", def_filter.target_grad_years)],
        allow_unspecified_grad_year=bool(filters_raw.get("allow_unspecified_grad_year", def_filter.allow_unspecified_grad_year)),
    )

    def_poll = PollingConfig()
    poll_cfg = PollingConfig(
        tier2_min_interval_minutes=int(polling_raw.get("tier2_min_interval_minutes", def_poll.tier2_min_interval_minutes)),
        tier3_min_interval_minutes=int(polling_raw.get("tier3_min_interval_minutes", def_poll.tier3_min_interval_minutes)),
        concurrency=int(polling_raw.get("concurrency", def_poll.concurrency)),
        timeout_seconds=int(polling_raw.get("timeout_seconds", def_poll.timeout_seconds)),
        retries=int(polling_raw.get("retries", def_poll.retries)),
        user_agent=str(polling_raw.get("user_agent", def_poll.user_agent)),
    )

    def_alerts = AlertsConfig()
    alerts_cfg = AlertsConfig(
        email_enabled=bool(alerts_raw.get("email_enabled", def_alerts.email_enabled)),
        max_jobs_per_email=int(alerts_raw.get("max_jobs_per_email", def_alerts.max_jobs_per_email)),
        daily_digest_hour_ist=int(alerts_raw.get("daily_digest_hour_ist", def_alerts.daily_digest_hour_ist)),
        ntfy_topic=str(alerts_raw.get("ntfy_topic", def_alerts.ntfy_topic)),
    )

    def_export = ExportConfig()
    export_cfg = ExportConfig(
        excel_path=str(export_raw.get("excel_path", def_export.excel_path)),
    )

    def_limits = LimitsConfig()
    limits_cfg = LimitsConfig(
        disable_after_consecutive_404=int(limits_raw.get("disable_after_consecutive_404", def_limits.disable_after_consecutive_404)),
        close_after_missed_cycles=int(limits_raw.get("close_after_missed_cycles", def_limits.close_after_missed_cycles)),
        empty_streak_before_close=int(limits_raw.get("empty_streak_before_close", def_limits.empty_streak_before_close)),
    )

    return Config(
        filters=filter_cfg,
        polling=poll_cfg,
        alerts=alerts_cfg,
        export=export_cfg,
        limits=limits_cfg,
    )
