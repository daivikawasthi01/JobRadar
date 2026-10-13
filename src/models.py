"""Data models for JobRadar."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    name: str
    ats: str
    slug: str
    tier: int

    @property
    def key(self) -> str:
        return f"{self.ats}:{self.slug}"


@dataclass
class Job:
    job_id: str  # f"{ats}:{slug}:{native_id}" (native_id as str)
    company_key: str  # Company.key
    company: str  # display name
    ats: str
    title: str
    location: str  # raw string, "" if unknown
    url: str  # direct apply/view link
    description: str  # PLAIN TEXT (HTML already stripped), "" if unknown
    posted_at: str | None  # ISO UTC "Z" or None
    salary: str | None
    remote: bool | None  # None if unknown
