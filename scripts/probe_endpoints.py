"""Script to probe live ATS endpoints, print structure, and save sample fixtures.

Usage:
    python scripts/probe_endpoints.py [--greenhouse SLUG] [--lever SLUG] [--ashby SLUG]
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error


GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

HEADERS = {
    "User-Agent": "JobRadar/1.0 (personal job search)"
}


def fetch_url(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            return status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        raise


def probe_greenhouse(slug: str, fixtures_dir: Path) -> dict:
    url = GREENHOUSE_URL.format(slug=slug)
    print(f"\n--- Probing Greenhouse ({slug}) ---")
    print(f"URL: {url}")
    status, body = fetch_url(url)
    print(f"HTTP Status: {status}")
    if status != 200:
        raise RuntimeError(f"Greenhouse probe failed with status {status}")

    data = json.loads(body)
    print(f"Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    print(f"Total jobs returned: {len(jobs)}")
    if jobs:
        print(f"Sample job keys: {list(jobs[0].keys())}")
        print("Sample job overview:")
        for k in ["id", "title", "absolute_url", "location", "updated_at", "first_published"]:
            print(f"  {k}: {jobs[0].get(k)}")

    # Save first ~5 jobs as fixture
    sample_data = dict(data)
    sample_data["jobs"] = jobs[:5]
    fixture_path = fixtures_dir / "greenhouse_sample.json"
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, indent=2)
    print(f"Saved fixture to {fixture_path} (containing {len(sample_data['jobs'])} jobs)")
    return data


def probe_lever(slug: str, fixtures_dir: Path) -> list:
    url = LEVER_URL.format(slug=slug)
    print(f"\n--- Probing Lever ({slug}) ---")
    print(f"URL: {url}")
    status, body = fetch_url(url)
    print(f"HTTP Status: {status}")
    if status != 200:
        raise RuntimeError(f"Lever probe failed with status {status}")

    data = json.loads(body)
    print(f"Top-level type: {type(data).__name__}")
    if isinstance(data, list):
        print(f"Total postings returned: {len(data)}")
        if data:
            print(f"Sample posting keys: {list(data[0].keys())}")
            print("Sample posting overview:")
            for k in ["id", "text", "hostedUrl", "categories", "createdAt", "workplaceType", "salaryRange"]:
                print(f"  {k}: {data[0].get(k)}")
        sample_data = data[:5]
    else:
        sample_data = data

    fixture_path = fixtures_dir / "lever_sample.json"
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, indent=2)
    print(f"Saved fixture to {fixture_path} (containing {len(sample_data)} jobs)")
    return data


def probe_ashby(slug: str, fixtures_dir: Path) -> dict:
    url = ASHBY_URL.format(slug=slug)
    print(f"\n--- Probing Ashby ({slug}) ---")
    print(f"URL: {url}")
    status, body = fetch_url(url)
    print(f"HTTP Status: {status}")
    if status != 200:
        raise RuntimeError(f"Ashby probe failed with status {status}")

    data = json.loads(body)
    print(f"Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    print(f"Total jobs returned: {len(jobs)}")
    if jobs:
        print(f"Sample job keys: {list(jobs[0].keys())}")
        print("Sample job overview:")
        for k in ["id", "title", "jobUrl", "location", "publishedAt", "isRemote", "isListed", "compensation"]:
            print(f"  {k}: {jobs[0].get(k)}")

    sample_data = dict(data)
    sample_data["jobs"] = jobs[:5]
    fixture_path = fixtures_dir / "ashby_sample.json"
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, indent=2)
    print(f"Saved fixture to {fixture_path} (containing {len(sample_data['jobs'])} jobs)")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe live ATS endpoints and save fixtures")
    parser.add_argument("--greenhouse", default="stripe", help="Greenhouse slug to probe")
    parser.add_argument("--lever", default="palantir", help="Lever slug to probe")
    parser.add_argument("--ashby", default="ramp", help="Ashby slug to probe")
    parser.add_argument("--fixtures-dir", default="tests/fixtures", help="Directory to save fixtures")
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    print("Probing ATS endpoints live...")
    probe_greenhouse(args.greenhouse, fixtures_dir)
    probe_lever(args.lever, fixtures_dir)
    probe_ashby(args.ashby, fixtures_dir)
    print("\nAll endpoints probed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
