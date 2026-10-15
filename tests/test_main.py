"""Tests for crawl orchestration and graceful deadline handling."""
import asyncio

from src.config import Config
from src.main import fetch_due_companies
from src.models import Company


class FakeAdapter:
    def __init__(self, delay=0, error=None):
        self.delay = delay
        self.error = error
        self.cancelled = False

    async def fetch(self, session, company, **kwargs):
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.error:
            raise self.error
        return []


def test_fetch_due_companies_returns_successes_errors_and_timed_out_boards(monkeypatch):
    import src.main as main

    fast = FakeAdapter()
    slow = FakeAdapter(delay=1)
    failed = FakeAdapter(error=RuntimeError("fixture failure"))
    monkeypatch.setattr(
        main,
        "ADAPTERS",
        {
            "greenhouse": fast,
            "lever": slow,
            "ashby": failed,
        },
    )
    companies = [
        Company("Fast", "greenhouse", "fast", 1),
        Company("Slow", "lever", "slow", 2),
        Company("Failing", "ashby", "failing", 3),
        Company("Unknown", "unknown", "unknown", 3),
    ]

    async def run():
        return await fetch_due_companies(
            session=None,
            companies=companies,
            cfg=Config(),
            budget_seconds=0.05,
        )

    results, skipped = asyncio.run(run())
    assert results[companies[0]] == []
    assert isinstance(results[companies[2]], RuntimeError)
    assert companies[1] in skipped
    assert companies[3] in skipped
    assert slow.cancelled is True
