"""Base protocol for ATS adapters."""
from typing import Any, Protocol
import aiohttp
from src.models import Company, Job


class Adapter(Protocol):
    """Protocol defining interface for each ATS adapter."""
    ats: str

    async def fetch(self, session: aiohttp.ClientSession, company: Company) -> list[Job]:
        """Fetch and parse jobs for the given company."""
        ...

    def parse(self, raw: Any, company: Company) -> list[Job]:
        """Pure parse function converting raw ATS data to standard Job records."""
        ...
