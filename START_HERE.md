# START HERE: how to feed this to an agentic AI IDE

Works with Claude Code, Cursor, Windsurf, Cline, Codex, or any agent that can read files, run a terminal, and edit code. `CLAUDE.md` and `AGENTS.md` (same content) are picked up automatically by most of them.

## 0. One-time setup (about 1.5 hours, you do this, not the AI)

1. Install **Python 3.11+**, **Git**, and your IDE/agent. Make a free **GitHub** account.
2. Create a **private** GitHub repo (name it `jobradar`). Private matters: your data and alerts live there.
3. Unzip this package, open a terminal inside the folder, then:
   ```bash
   git init
   git add .
   git commit -m "initial spec"
   git branch -M main
   git remote add origin https://github.com/<you>/jobradar.git
   git push -u origin main
   ```
4. No state branch setup is needed. The first GitHub Actions run creates a `state` release containing the compressed database and suppresses email during initial seeding.
5. Gmail app password (needed from Phase 5): Google Account → turn on 2-Step Verification → Security → App passwords → create one → copy the 16 characters.
6. GitHub repo → Settings → Secrets and variables → Actions → add `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO` (needed from Phase 6).
7. Locally, copy `.env.example` to `.env` and fill it in (never commit it).
8. Optional now, needed at Phase 7: convert your two company databases to CSV with a `name` column (plus `website` if you have it) and put them in `config/inputs/`.

## 1. Kickoff prompt (paste this first)

> Read `CLAUDE.md` and then `BUILD_SPEC.md` fully, and read `README.md` for the overview. Do not write any code yet. Reply with: (1) a 5-line summary of what we are building, (2) the list of phases, (3) anything in the spec that is ambiguous or that you think is wrong. Then wait.

Answer any questions it raises, then continue.

## 2. Phase prompts (paste ONE at a time, wait for the report, check it, then paste the next)

Use this template, changing the phase number:

> Execute **Phase N only** from `BUILD_SPEC.md`. Follow every rule in section B0. Run the phase's acceptance checks and show me the actual command output. If anything differs from the spec, list it. Then STOP and wait for my go-ahead.

| Phase | What it does | You check |
|---|---|---|
| 0 | Skeleton, config loader, CSV validation | `python -m src.main validate` exits 0; `pytest -q` green |
| 1 | Verifies the real ATS endpoints, saves fixtures, builds Greenhouse/Lever/Ashby adapters | It reports any field names that differed from the spec; fixtures exist in `tests/fixtures/` |
| 2 | SQLite store + new/closed job logic | All 11 store tests pass |
| 3 | Role / experience / location filters | All 24 filter test cases pass; skim the printed sample of 20 real jobs |
| 4 | Wires the `run` command (no email yet) | Dry run writes nothing; first run seeds silently; second run shows `new=0` |
| 5 | Email alerts + Excel export | Needs your `.env`. You receive the test email and a real alert; `jobs.xlsx` opens |
| 6 | GitHub Actions every 15 min | First run creates a `state` release with `jobs.db.xz` and logs its compressed size; second run restores it and shows `new=0` |
| 7 | Company discovery (`discover`) + `--merge` | Runs for hours, resumable; spot-check ~20 hits before `--merge` |
| 8, 9 | Optional: Workday/Workable/SmartRecruiters, custom pages | Only if you ask |

Optional monthly company source: run `python -m src.main discover-hn` to save company names from the latest Hacker News “Who is hiring?” thread under `config/inputs/`, then run `python -m src.main discover` to probe their ATS boards.
The separate weekly Common Crawl workflow screens five ATSs and opens a pull request with passing boards; review it before merging.

Phase 5 extra note: tell the agent how you load `.env` (`set -a; source .env; set +a`). Do not paste your app password into the chat.

## 3. When the agent goes wrong (copy-paste fixes)

- A test fails: *"Do not edit the test to make it pass. Explain why it fails, and tell me whether the code or the spec is wrong."*
- It adds extra stuff: *"That is out of scope per BUILD_SPEC.md section B14. Revert it and continue the current phase only."*
- It guesses an API field: *"Do not guess. Make the live call, show me the real response, and fix the adapter from that."*
- It tries to run the next phase: *"Stop. Only the current phase. Report and wait."*
- Context gets long or confused: start a new chat and paste the kickoff prompt again, then say *"We finished through Phase N. Continue with Phase N+1."*

## 4. After it works

1. Let it run for a few days. Skim the matches and note wrong ones (jobs that should not match, or that you missed).
2. Tell the agent: *"Here are 10 wrong matches with titles and descriptions. Update the filter rules, add each as a new test case in `tests/test_filters.py`, and show me the results."*
3. Hand-set `tier` to `1` for your 200-300 dream companies in `config/companies.csv`.
4. Every alert: apply within the hour, then message a recruiter or alum, and track it in a Google Sheet.

## 5. Files in this package

| File | Purpose |
|---|---|
| `BUILD_SPEC.md` | The full build instructions for the AI (authoritative) |
| `README.md` | Human-friendly overview and architecture |
| `CLAUDE.md` / `AGENTS.md` | Short rules the agent loads automatically |
| `config/config.yaml` | Filters, polling, alert settings |
| `config/companies.csv` | Active company list (3 unverified sample rows) |
| `config/seed_company_names.txt` | ~2,000 company names for `discover` |
| `config/seed_removed_names.txt` | Names I pruned (restore any you want) |
| `config/inputs/` | Drop your own company CSVs here |
| `.github/workflows/crawl.yml` | The 15-minute scheduler |
| `.env.example`, `.gitignore`, `requirements.txt` | Setup basics |
