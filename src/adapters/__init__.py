"""ATS adapters registry."""
from src.adapters.base import Adapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.adapters.ashby import AshbyAdapter
from src.adapters.smartrecruiters import SmartRecruitersAdapter
from src.adapters.workable import WorkableAdapter
from src.adapters.workday import WorkdayAdapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),
    "workable": WorkableAdapter(),
    "workday": WorkdayAdapter(),
}

__all__ = [
    "Adapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "AshbyAdapter",
    "SmartRecruitersAdapter",
    "WorkableAdapter",
    "WorkdayAdapter",
    "ADAPTERS",
]
