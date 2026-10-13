from pathlib import Path
import sys

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import aiohttp
from src.adapters.ashby import AshbyAdapter
from src.adapters.greenhouse import GreenhouseAdapter
from src.adapters.lever import LeverAdapter
from src.models import Company


async def run_smoke() -> int:
    companies = [
        Company(name="Stripe", ats="greenhouse", slug="stripe", tier=1),
        Company(name="Palantir", ats="lever", slug="palantir", tier=2),
        Company(name="Ramp", ats="ashby", slug="ramp", tier=2),
    ]

    adapters = {
        "greenhouse": GreenhouseAdapter(),
        "lever": LeverAdapter(),
        "ashby": AshbyAdapter(),
    }

    headers = {"User-Agent": "JobRadar/1.0 (personal job search)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        print("Running live smoke test for ATS adapters...")
        all_ok = True
        for comp in companies:
            adapter = adapters[comp.ats]
            try:
                jobs = await adapter.fetch(session, comp)
                print(f"[OK] {comp.name} ({comp.ats}:{comp.slug}) -> {len(jobs)} jobs fetched")
                if jobs:
                    sample = jobs[0]
                    print(f"     Sample: '{sample.title}' ({sample.location or 'No loc'}) | {sample.url}")
            except Exception as e:
                print(f"[FAIL] {comp.name} ({comp.ats}:{comp.slug}) -> Error: {e}", file=sys.stderr)
                all_ok = False

        if all_ok:
            print("\nSmoke test passed: all 3 adapters successfully fetched live jobs.")
            return 0
        else:
            print("\nSmoke test failed for one or more adapters.", file=sys.stderr)
            return 1


def main() -> int:
    return asyncio.run(run_smoke())


if __name__ == "__main__":
    sys.exit(main())
