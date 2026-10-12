# JobRadar: agent instructions

You are building JobRadar, a crawler that watches company career pages (via public ATS JSON endpoints), detects new fresher/entry-level jobs in India, saves them to Excel, and emails alerts.

**The single source of truth is `BUILD_SPEC.md`. Read it fully before doing anything.**

Hard rules (details in BUILD_SPEC.md §B0):
1. Work ONE phase at a time. Run the phase's acceptance checks, report results, then STOP and wait for the human.
2. Never invent API endpoints or response fields. Verify live (Phase 1), save fixtures, follow reality, report differences.
3. Do not expand scope. No extra features, frameworks, ORMs, Selenium, dashboards, or ATS adapters beyond the current phase.
4. Never scrape LinkedIn, Naukri, Indeed, Glassdoor, or any site that forbids it.
5. No secrets in code, logs, tests, or commits. Credentials come only from environment variables.
6. Tests never touch the network; use fixtures in `tests/fixtures/`. Never silently change a test to make it pass: if a spec test case looks wrong, tell the human.
7. One company's failure must never crash a run or close its jobs.
8. All stored timestamps are UTC ISO-8601 ending in `Z`.
9. If the spec is ambiguous or contradicts reality, ask the human instead of guessing.
10. Pre-supplied files (config, workflow, .gitignore, etc.) are listed at the top of BUILD_SPEC.md: verify them, don't blindly recreate them.

Stack: Python 3.11+, sqlite3 (no ORM), aiohttp, pyyaml, openpyxl, pandas, beautifulsoup4, pytest. Run as `python -m src.main ...`.
