"""ATS adapters registry."""
from src.adapters.base import Adapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.adapters.ashby import AshbyAdapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}

__all__ = ["Adapter", "GreenhouseAdapter", "LeverAdapter", "AshbyAdapter", "ADAPTERS"]
