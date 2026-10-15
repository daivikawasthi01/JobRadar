> **Note for AI agents:** `BUILD_SPEC.md` is the authoritative build instruction. This README is the high-level overview. If they conflict (e.g. application tracker, tiers, sheets), follow `BUILD_SPEC.md`.

# JobRadar: Fresher Job Crawler & Instant Alert System

A crawler that watches thousands of company career pages, detects **newly posted** jobs within minutes, filters them for **fresher / entry-level roles** (Associate SWE, Full Stack, AI/ML Engineer, etc.), saves everything to **Excel**, and sends an **email alert** so you can apply while you're among the first applicants.

---

## 1. Why this exists

- Most entry-level roles get hundreds of applicants within 24-48 hours. Applying early matters.
- Only a small share of postings are truly entry-level (~5% explicitly say "fresher"), so manual searching is slow and noisy.
- Most Indian postings (~90%) don't list salary/CTC, so the sheet keeps a salary column that's usually empty.
- Jobs are scattered across thousands of company sites. This tool collects them in one place.

**Goal:** apply to the right jobs faster than other candidates, then pair each application with human outreach (referral / recruiter message).

---

## 2. What the system does

1. **Crawls** career boards for 2,000-5,000+ companies using public ATS endpoints.
2. **Normalizes** every job into one standard format.
3. **Detects new jobs** by comparing against a database of already-seen jobs.
4. **Filters** by role keywords, experience (min years), and location.
5. **Alerts** you by email (optionally ntfy push) with a table of new matches.
6. **Exports** all jobs and matches to Excel (`jobs.xlsx`), newest first.
7. **Tracks job lifecycle:** marks jobs as closed when they disappear from the board.
8. **Tracks your applications** (status, outreach, follow-up dates).

---

## 3. How it works (key idea)

You do **not** need 5,000 custom scrapers. Most companies use a handful of Applicant Tracking Systems (ATS). Many ATS platforms expose public job data as JSON. So:

> ~7 ATS adapters + a big list of company slugs = thousands of career sites.

Estimated coverage (approximate, unverified):

| ATS | Approx. boards | Access method |
|---|---|---|
| Greenhouse | 6,000-8,000 | Public JSON API |
| Lever | 3,000-4,000 | Public JSON API |
| Ashby | 2,000-3,000 | Public JSON API |
| SmartRecruiters | 3,000-4,000 | Public JSON API |
| Workable | 5,000-10,000 | Public JSON API |
| Workday | 2,000-4,000 | Per-tenant JSON endpoint (harder) |
| Zoho Recruit | Thousands (messy) | HTML / feeds |

Realistic first target: **2,000-5,000 companies**, yielding roughly **100k-300k open postings**, of which a few thousand are fresher-relevant.

---

## 4. Architecture

```
                 ┌────────────────────────┐
                 │  companies.csv / DB     │  company name, ATS, slug, priority
                 └───────────┬────────────┘
                             │
                  ┌──────────▼───────────┐
                  │  Scheduler            │  GitHub Actions cron / VM cron
                  └──────────┬───────────┘
                             │ every 10-30 min
                  ┌──────────▼───────────┐
                  │  Async Fetcher        │  aiohttp, rate limits, retries
                  │  (per-ATS adapters)   │
                  └──────────┬───────────┘
                             │ raw JSON
                  ┌──────────▼───────────┐
                  │  Normalizer           │  → standard Job record
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │  Deduper / Diff       │  compare with SQLite (seen jobs)
                  └──────────┬───────────┘
              new jobs only  │
                  ┌──────────▼───────────┐
                  │  Filter Engine        │  role + experience + location
                  └───────┬──────┬───────┘
                          │      │
              ┌───────────▼─┐  ┌─▼──────────────┐
              │ Notifier     │  │ Excel Exporter │
              │ Email / ntfy │  │ jobs.xlsx      │
              └──────────────┘  └────────────────┘
                          │
                  ┌───────▼────────┐
                  │ Application     │  status, outreach, follow-ups
                  │ Tracker         │
                  └─────────────────┘
```

### Components

| Component | Responsibility |
|---|---|
| **Company registry** | List of companies with ATS type, slug, and priority tier |
| **Adapters** | One module per ATS: fetch + parse into standard records |
| **Fetcher** | Async HTTP, concurrency limits, timeouts, retries, backoff |
| **Normalizer** | Maps each ATS's fields into the standard schema |
| **Store (SQLite)** | Persistent record of every job and when it was first/last seen |
| **Diff engine** | Finds jobs not seen before; finds jobs that disappeared |
| **Filter engine** | Role, experience, location, exclusion rules |
| **Notifier** | Batched email alerts; instant alerts for priority companies |
| **Exporter** | Writes Excel with formatting, sorted newest first |
| **Tracker** | Your application pipeline |

---

## 5. Tech stack

- **Language:** Python 3.11+
- **HTTP:** `aiohttp` + `asyncio` (fast concurrent polling); `requests` for simple cases
- **HTML parsing (fallback):** `BeautifulSoup4`; `Playwright` only for JS-heavy sites
- **Data:** `sqlite3` (built in), `pandas`
- **Excel:** `openpyxl`
- **Email:** `smtplib` with Gmail SMTP + app password
- **Config:** `pyyaml`
- **Scheduling:** GitHub Actions (start) → Oracle Cloud free VM or cheap VPS (later)
- **Testing:** `pytest`

---

## 6. Project structure

```
jobradar/
├── README.md
├── requirements.txt
├── config.yaml                 # filters, alert settings, polling tiers
├── data/
│   ├── companies.csv           # name, ats, slug, tier
│   ├── jobs.db                 # SQLite state
│   └── jobs.xlsx               # output
├── src/
│   ├── main.py                 # entry point: one full crawl cycle
│   ├── registry.py             # loads companies
│   ├── fetcher.py              # async HTTP client, retries, rate limits
│   ├── adapters/
│   │   ├── base.py             # Adapter interface
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── smartrecruiters.py
│   │   ├── workable.py
│   │   └── workday.py
│   ├── models.py               # Job dataclass
│   ├── store.py                # SQLite read/write, diffing
│   ├── filters.py              # role / experience / location logic
│   ├── notify.py               # email + optional ntfy
│   ├── export.py               # Excel writer
│   ├── tracker.py              # application tracking
│   └── discovery.py            # find new company slugs
├── tests/
│   ├── test_filters.py
│   ├── test_adapters.py
│   └── fixtures/               # saved sample API responses
└── .github/workflows/
    └── crawl.yml
```

---

## 7. Data model

### Standard `Job` record

| Field | Description |
|---|---|
| `job_id` | `{ats}:{company_slug}:{native_id}` (unique key) |
| `title` | Job title |
| `company` | Company name |
| `location` | Raw location string |
| `country` | Parsed country (India / US / other) |
| `remote` | Remote / hybrid / onsite if known |
| `url` | Direct apply link |
| `posted_at` | Posted/updated date from the ATS, if provided |
| `description` | Full text (used for experience parsing; stored zlib-compressed in SQLite) |
| `min_exp` | Parsed minimum years of experience (nullable) |
| `max_exp` | Parsed maximum years (nullable) |
| `salary` | Salary/CTC text if present |
| `ats` | Source platform |
| `first_seen` | When your crawler first saw it |
| `last_seen` | Last cycle in which it was still listed |
| `status` | `open` / `closed` |
| `matched` | Whether it passed your filters |

### SQLite tables

- `jobs`: all fields above, primary key `job_id`
- `companies`: name, ats, slug, tier, last_crawled, last_error
- `applications`: job_id, applied_on, status, contact_name, contact_link, outreach_sent, follow_up_on, notes
- `alerts_sent`: job_id, sent_at (prevents duplicate alerts)

Descriptions remain available but are zlib-compressed in the database, with existing plain-text rows migrated automatically on startup. After a successful non-dry-run crawl, jobs closed for more than 60 days are pruned and SQLite is vacuumed. GitHub Actions stores the database as an `xz`-compressed asset on the `state` release, logs the compressed size, and warns above 70 MiB.

---

## 8. ATS adapters

Each adapter implements: `async fetch(company) -> list[Job]`. Endpoints below are the commonly used public ones; **verify each before relying on it**, since vendors change them.

| ATS | Endpoint pattern |
|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` |
| Lever | `GET https://api.lever.co/v0/postings/{slug}?mode=json` |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{slug}` |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings` |
| Workable | `POST https://apply.workable.com/api/v3/accounts/{slug}/jobs` |
| Workday | `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` |

Adapter rules:
- Never crash the whole cycle on one company's failure. Log it and continue.
- Mark a company as "dead" after repeated 404s so you stop polling it.
- Greenhouse/Lever may need a second call per job for the full description; fetch it only for **new** jobs to save time.

---

## 9. Building the company list

This is the biggest piece of manual work. Sources:

1. **Open GitHub lists** of Greenhouse/Lever/Ashby company slugs (search "greenhouse company slugs", "lever companies list").
2. **Slug guessing:** take company names from startup lists and test `boards-api.greenhouse.io/v1/boards/{name}`; a 200 response means a hit.
3. **Indian product/startup lists:** unicorns, Y Combinator India founders, funded startups (Wellfound, Crunchbase free tier, Tracxn lists).
4. **Careers-page URL detection:** visit `company.com/careers`, check whether it redirects or embeds `boards.greenhouse.io/xyz`, `jobs.lever.co/xyz`, `jobs.ashbyhq.com/xyz`, and so on.
5. **Manual additions** for companies you specifically want.

`companies.csv` format:

```
name,ats,slug,tier
Razorpay,greenhouse,razorpaysoftwareprivatelimited,1
Postman,greenhouse,postman,1
Zepto,lever,zepto,1
```

**Tiers** control polling frequency:
- **Tier 1:** your top 200-300 dream companies, polled every 10-15 min
- **Tier 2:** the rest, polled hourly

---

## 10. Filtering logic

### 10.1 Role filter
Include if the title matches any of:

```
associate software engineer, software engineer I, SDE-1, SDE 1, junior developer,
graduate engineer trainee, GET, full stack, fullstack, backend engineer,
frontend engineer, AI engineer, ML engineer, machine learning, data engineer,
python developer, software developer, trainee, intern (optional), new grad
```

Exclude if the title contains:

```
senior, sr., lead, principal, staff, manager, director, head of, architect, VP
```

### 10.2 Experience filter
Parse the description and title with regexes such as:

```python
PATTERNS = [
    r'(\d+)\s*[-–to]+\s*(\d+)\s*\+?\s*years?',   # "0-2 years", "1 to 3 years"
    r'(\d+)\s*\+\s*years?',                       # "2+ years"
    r'(?:minimum|at least|min\.?)\s*(\d+)\s*years?',
    r'up to\s*(\d+)\s*years?',
    r'(fresher|freshers|new grad|recent graduate|entry[- ]level|0 years)',
]
```

Rules:
- Extract `min_exp`. **Keep if `min_exp <= 2`** (configurable).
- If no experience is stated, fall back to the title: "Associate", "Junior", "SDE-1", "Trainee", "Graduate" → entry-level; "Senior"/"Lead" → reject; plain titles → "unknown" (keep, but flag).
- Handle edge cases: "3-5 years" → reject, "preferred 5 years" in a nice-to-have section is a known false-positive risk, so log borderline cases for review.

### 10.3 Location filter
- Parse the location string into country (India, US, UK, Canada, and so on).
- Config option: `countries: [India]` plus `include_remote: true`.
- Optional city whitelist: Bengaluru, Hyderabad, Pune, Chennai, Mumbai, Delhi NCR.

### 10.4 Scoring (optional, later)
Give each match a score (role match + experience fit + company tier + keyword overlap with your resume) and sort by score.

---

## 11. Detecting "new" and "live" jobs

- **New:** `job_id` not present in the DB → insert with `first_seen = now`.
- **Live:** present in the latest fetch → update `last_seen`, keep `status = open`.
- **Closed:** was open, missing from the latest *successful* fetch of that company → set `status = closed`. (If a company's fetch fails, do **not** mark its jobs closed.)
- **First run:** the very first crawl will see everything as "new". Seed the DB silently (no alerts) and only alert from the second run on.

---

## 12. Alerts

### Email (primary)
- Gmail SMTP with an **app password** (needs 2-step verification enabled; never use your real password).
- **Batched:** one email per cycle containing a table of all new matches (title, company, location, experience, link).
- **Instant mode:** a separate email immediately for Tier 1 companies.
- Subject prefix `[New Job]` so you can filter it.

### Getting phone-level instant notifications
1. Create a Gmail filter: subject contains `[New Job]` → apply label, mark Important.
2. In the Gmail app → Settings → Notifications → set to **High priority only** (or enable notifications for that label).

### ntfy.sh (optional)
Free push notifications: the script sends one HTTP POST to `ntfy.sh/<your-secret-topic>` and your phone buzzes. Faster than email.

### Dedupe
Record every alerted `job_id` in `alerts_sent` so you never get the same job twice.

---

## 13. Excel output

`jobs.xlsx` with sheets:

| Sheet | Contents |
|---|---|
| **Matches** | Filtered, fresher-relevant jobs, newest first |
| **All Jobs** | Everything crawled |
| **Applications** | Your tracker (status, contact, follow-up date) |
| **Stats** | Companies crawled, jobs found, new today, failures |

Columns: Role, Company, Location, Country, Min Exp, Posted, First Seen, Salary, Source, Link, Contact (for you to fill in), Status.

Formatting: frozen header, filters on, clickable links, conditional colour for new-today rows.

---

## 14. Scheduling and "real time"

There is no push from career sites, so real time = **frequent polling + alert only on new matches**.

| Option | Pros | Cons |
|---|---|---|
| **GitHub Actions** | Free, no laptop needed | Cron can lag 5-30 min; state must be committed back to the repo |
| **Oracle Cloud free VM / cheap VPS** | Reliable, runs every 10 min | Needs setup |
| **Your laptop (cron / Task Scheduler)** | Easiest start | Only runs when on |

**Recommended path:** start with GitHub Actions every 15-30 min → move to a VM later (code stays identical).

Polling strategy:
- Tier 1 every 10-15 min, Tier 2 hourly
- Use `ETag` / `If-Modified-Since` where supported
- Concurrency cap (e.g. 20-50 at a time) plus small random delays

The repository workflow in `.github/workflows/crawl.yml` downloads and restores `jobs.db.xz` from the `state` GitHub Release, runs the crawler, then replaces the release asset with the newly compressed database. On the first run, it seeds state with email suppressed. Keep the old `state` branch until the new workflow has succeeded a couple of times.

Keep the repo **private** (your DB contains your application data), and store credentials only in GitHub **Secrets**.

---

## 15. Configuration (`config.yaml`)

```yaml
filters:
  roles_include: [associate software engineer, sde-1, full stack, backend, ai engineer, ml engineer, graduate engineer trainee]
  roles_exclude: [senior, sr., lead, principal, staff, manager, director, architect]
  max_min_experience: 2
  countries: [India]
  include_remote: true

polling:
  tier1_minutes: 10
  tier2_minutes: 60
  concurrency: 30
  timeout_seconds: 15
  retries: 3

alerts:
  email_enabled: true
  batch: true
  instant_for_tier1: true
  ntfy_topic: ""          # optional

export:
  excel_path: data/jobs.xlsx
```

---

## 16. End-to-end build plan

**Phase 0: Setup (Day 1)**
- Create the repo, virtual env, `requirements.txt`, folder structure.

**Phase 1: Core crawl (Days 2-3)**
- Define the `Job` model and the SQLite schema.
- Build the Greenhouse and Lever adapters.
- Crawl 20-50 companies, print results.

**Phase 2: Diff and storage (Day 4)**
- Insert jobs, detect new/closed, handle first-run seeding.

**Phase 3: Filters (Days 5-6)**
- Role, experience, and location filters, plus unit tests against real postings.

**Phase 4: Excel export (Day 7)**
- Multi-sheet formatted output.

**Phase 5: Email alerts (Day 8)**
- Gmail SMTP, batched table, dedupe via `alerts_sent`.

**Phase 6: Automation (Days 9-10)**
- GitHub Actions workflow, secrets, state commit-back, failure handling.

**Phase 7: Scale up (Days 11-16)**
- Async fetcher, more adapters (Ashby, SmartRecruiters, Workable, Workday).
- Company discovery scripts; grow to 1,000+ companies.
- Tier-based polling.

**Phase 8: Polish (Days 17-21)**
- Scoring, application tracker, stats sheet, ntfy push, README + demo GIF, optional small web dashboard.

---

## 17. Application workflow (where the real edge is)

A fast alert only helps if you act on it. For every match:

1. **Apply within the first hours.**
2. **Message a human within an hour:** a recruiter or team engineer on LinkedIn, 3-4 lines: who you are, the role, one specific project.
3. **Ask for a referral** from alumni at that company.
4. **Tailor the resume:** mirror the job description's keywords honestly; one page, single column.
5. **Log everything** in the tracker; follow up once after 5-7 days.

### Outreach template

> Hi [Name], I'm [You], a recent [degree] graduate. I just applied for the [Role] at [Company]. I've built [specific project, one line with a result], which relates to [something about their product/team]. I'd really appreciate any advice, or a referral if you feel I'm a fit. Happy to share my resume. Thanks!

---

## 18. Other things that improve your chances

- **Public project:** this crawler on GitHub (clear README, demo, numbers) is a strong portfolio piece. Two or three solid projects beat many tutorial clones.
- **Look beyond big companies:** startups hire without posting; email founders and engineering leads.
- **Internships / contract / intern-to-hire** roles get fewer applicants and often convert.
- **Prepare in parallel:** daily DSA practice, mock interviews, and system-design basics.

---

## 19. Risks, limits, and ethics

- **Do not scrape LinkedIn, Naukri, or Indeed.** Their terms forbid it and they block quickly. Stick to company career pages and public ATS endpoints.
- Respect `robots.txt`, use sensible rate limits, and identify your crawler with a User-Agent string.
- Use data for **personal job hunting**; don't republish or resell it.
- Endpoints change: expect to maintain adapters. Keep saved sample responses as test fixtures.
- Experience parsing is heuristic; expect some false positives/negatives. Review borderline cases.
- Salary data will be mostly empty (~9% of Indian postings list CTC).
- GitHub Actions scheduling is best-effort; for tighter timing use a VM.
- Never commit credentials. Use Secrets and `.gitignore`.

---

## 20. Future ideas

- Resume-to-job match scoring (keyword overlap or embeddings)
- Auto-generate a tailored cover note per job
- Contact finder: pull recruiter names from job pages for outreach
- Telegram/WhatsApp/ntfy push channels
- Small web dashboard with filters and status tracking
- Browser extension to log applications in one click
- Weekly insights: which companies hire freshers most, salary trends

---

## 21. Success metrics

- Companies covered (target: 2,000+)
- Jobs crawled per cycle and new jobs per day
- Time from posting to your alert (target: under 30 min)
- Applications per week, outreach messages sent, replies received, interviews booked

---

## 22. Quick start (once built)

```bash
git clone <your-private-repo>
cd jobradar
pip install -r requirements.txt
cp config.example.yaml config.yaml      # edit filters
export GMAIL_USER=you@gmail.com
export GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
export ALERT_TO=you@gmail.com
python src/main.py                      # first run seeds the DB silently
python src/main.py                      # later runs alert on new matches
```
