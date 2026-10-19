# JobRadar: BUILD SPEC (for Claude Code)

> **PRE-SUPPLIED FILES (read first):** this repo already contains `README.md`, `BUILD_SPEC.md`, `CLAUDE.md`, `AGENTS.md`, `START_HERE.md`, `.gitignore`, `.env.example`, `requirements.txt`, `config/config.yaml`, `config/companies.csv`, `config/seed_company_names.txt`, `config/seed_removed_names.txt`, `config/inputs/`, and `.github/workflows/crawl.yml`. In Phase 0 and Phase 6, **verify these against this spec instead of recreating them**, and only fix real mismatches (tell the human what you changed). If `README.md` and this file ever disagree, **this file wins**.

> **How to use:** put this file and `README.md` in the root of an empty private Git repo. Open Claude Code in that folder and say:
> *"Read BUILD_SPEC.md fully. Execute Phase 0 only. Stop when its acceptance checks pass and report."*
> Then repeat for each next phase. **Never ask for the whole thing in one go.** Small phases with checks are what prevent mistakes.

---

# PART A: WHAT THE HUMAN MUST DO (Claude Code cannot do these)

| # | Task | When | Time |
|---|---|---|---|
| A1 | Install Python 3.11+, Git, and Claude Code. Create a GitHub account. | Before Phase 0 | 30-60 min |
| A2 | Create a **private** GitHub repo, clone it locally. | Before Phase 0 | 5 min |
| A3 | Turn on Google 2-Step Verification, then create a Gmail **App Password** (Google Account → Security → App passwords). Save the 16-character code. | Before Phase 5 | 10 min |
| A4 | No manual state-branch setup is needed; the first successful Phase 6 workflow creates the `state` GitHub Release. | Phase 6 | automatic |
| A5 | Add GitHub repo Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO` (Repo → Settings → Secrets and variables → Actions). | Before Phase 6 | 5 min |
| A6 | Build the company list. Put `seed_company_names.txt` (~1,000 names, included) into `config/`. Convert your **two existing company databases** to CSV with a `name` column (plus `website` if you have it) and put them in `config/inputs/`. Run `discover` (Phase 7; it runs for hours and is resumable), spot-check ~20 random hits for wrong matches, then run `discover --merge`. Finally, **hand-edit `tier` to `1`** for your 200-300 dream companies. | Phase 7+ | 1-2 hrs of your time, plus hours of unattended running |
| A7 | Review the first 50-100 matches yourself and report false positives/negatives so filters can be tuned. | After Phase 3 and 6 | 2-3 hrs |
| A8 | Set Gmail filter + phone notifications (README §12). | After Phase 5 | 10 min |
| A9 | Keep your resume, LinkedIn, GitHub profile, and outreach message ready. The crawler is useless without fast action. | Parallel | ongoing |
| A10 | Track applications in a **Google Sheet** you maintain by hand. (The program does not manage this. See §B14.) | Ongoing | ongoing |

## Realistic time estimate

| Stage | Estimate |
|---|---|
| Claude Code writes + tests Phases 0-6 (Greenhouse/Lever/Ashby, filters, email, Actions) | **3-6 hours of wall-clock**, plus your review/approvals; realistically spread over 1-2 days |
| Your manual setup (A1-A5) | ~1.5 hours |
| Company list to ~1,000+ companies (A6) | 1-2 weeks of on-and-off effort, 2-4 hrs per session |
| Filter tuning against real data (A7) | 2-3 hrs per round, plan 2-3 rounds |
| **First useful alerts running** | **About 2 days** |
| **Mature version (2,000+ companies, tuned filters)** | **About 2 weeks** |

These are estimates, not guarantees. The slowest part is the company list, not the code.

---

# PART B: INSTRUCTIONS FOR CLAUDE CODE

## B0. Operating rules (read first, obey always)

1. **Work one phase at a time.** After finishing a phase, run its acceptance checks, print the results, then **STOP** and wait for the human.
2. **Do not invent API endpoints or response fields.** Phase 1 verifies each ATS endpoint with a live call and saves real responses as fixtures. If a field name in this spec differs from reality, **follow reality**, update the adapter and fixture, and tell the human what differed.
3. **Do not expand scope.** Do not add features, frameworks, ORMs, web dashboards, Selenium, or any ATS not listed for the current phase.
4. **Never scrape LinkedIn, Naukri, Indeed, Glassdoor, or any site that forbids scraping.** Only public ATS JSON endpoints and company career pages.
5. **No secrets in code, logs, tests, or commits.** Read credentials only from environment variables. `.env` must be in `.gitignore`.
6. **Pure functions where possible.** Parsing and filtering take data in and return data out (no network, no DB). This makes them testable offline.
7. **Tests never hit the network.** Tests use saved fixtures in `tests/fixtures/`. Live checks live only in `scripts/`.
8. **One company's failure must never crash a run.** Catch, log, record, continue.
9. **All timestamps are stored in UTC** as ISO-8601 strings ending in `Z` (e.g. `2026-10-12T04:30:00Z`). Convert to IST (UTC+5:30) only for display in emails.
10. **If something in this spec is ambiguous or contradicts reality, ask the human. Do not guess silently.**
11. After Phase 0, run `pip freeze` for the packages used and pin the versions in `requirements.txt`.

## B1. Fixed decisions (do not change)

- Python 3.11+, standard library `sqlite3` (no ORM), `aiohttp` for HTTP, `pyyaml`, `openpyxl`, `pandas`, `beautifulsoup4`, `pytest`.
- Package layout `src/` run as `python -m src.main ...`.
- State lives in `data/` (SQLite DB + Excel). Config lives in `config/`.
- Email via Gmail SMTP over SSL: `smtp.gmail.com`, port `465`.
- Scheduler: GitHub Actions every 15 minutes (Phase 6). State is stored as a compressed `jobs.db.xz` asset on the `state` GitHub Release.

## B2. Repository layout (create exactly this)

```
.
├── BUILD_SPEC.md
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config/
│   ├── config.yaml
│   ├── companies.csv
│   ├── seed_company_names.txt  # provided; ~1,000 unverified names
│   ├── inputs/                 # human drops extra company CSV/TXT files here
│   ├── companies_candidates.csv   # written by `discover`
│   ├── unsupported_ats_hits.csv   # written by `discover` (Workday etc., for Phase 8)
│   └── custom_pages.csv           # written by `discover` (JSON-LD pages, for Phase 9)
├── data/                       # runtime state (gitignored; stored in the `state` release asset)
├── scripts/
│   ├── probe_endpoints.py      # live check, saves fixtures
│   ├── smoke_live.py           # live end-to-end check on a few companies
│   ├── discover_ats.py         # probe seeded company names against public ATS boards
│   └── harvest_slugs.py        # weekly Common Crawl ATS board discovery
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── registry.py
│   ├── fetcher.py
│   ├── store.py
│   ├── filters.py
│   ├── notify.py
│   ├── export.py
│   ├── discovery.py
│   ├── textutil.py
│   └── adapters/
│       ├── __init__.py
│       ├── base.py
│       ├── greenhouse.py
│       ├── lever.py
│       ├── ashby.py
│       ├── recruitee.py
│       ├── bamboohr.py
│       ├── breezy.py
│       └── jsonld.py
├── tests/
│   ├── fixtures/
│   ├── test_textutil.py
│   ├── test_adapters.py
│   ├── test_filters.py
│   ├── test_store.py
│   └── test_notify.py
└── .github/workflows/
    ├── crawl.yml
    └── harvest-slugs.yml
```

`.gitignore` must include: `.env`, `data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.venv/`.

## B3. Data contracts

### B3.1 `Company` (from `config/companies.csv`)

CSV header (exact): `name,ats,slug,tier` (an optional 5th column `extra` is allowed only from Phase 8 onward; before that, reject files that have it)

- `ats` ∈ `greenhouse | lever | ashby | workable | smartrecruiters | workday | jsonld | recruitee | bamboohr | breezy`
- `slug`: the identifier in the board URL
- For `jsonld`, the optional `extra` column is required and contains the absolute public page URL.
- `tier` ∈ `1 | 2 | 3` (this is the **base tier**, set by the human or by `discover`):
  - **Tier 1:** dream companies, polled every run (every ~15 min).
  - **Tier 2:** polled about hourly.
  - **Tier 3:** companies with no matching jobs right now, polled every ~4 hours. **Automatically promoted to effective Tier 2** while they have at least one open matched job (see B9.2). Never auto-promoted to Tier 1.
- Lines starting with `#` are comments. Blank lines ignored.
- Duplicate `(ats, slug)` rows: keep first, log a warning.
- `company_key = f"{ats}:{slug}"`

### B3.1a Company stage metadata (`config/company_meta.csv`)

Header: `name,segment,team_size,hq_country,source`; `#` comment lines allowed. Rows match `companies.csv` by `discovery.normalize_company_name(name)`, so `companies.csv` keeps its 4/5-column format.
- `segment` ∈ `seed | series_a | series_b | series_c_plus | midsize | unknown | large` (that is also the alert sort order). Anything else is read as `unknown` with a warning.
- When only headcount is known, `registry.estimate_segment(team_size)` maps ≤30 → seed, ≤150 → series_a, ≤400 → series_b, ≤2000 → midsize, else large. This is an estimate.
- Imports (`discover-yc`) add or refresh rows but never overwrite a row whose `source` is `manual`.
- `run` copies `segment` and `team_size` into the `companies` table on every sync (new nullable columns `segment TEXT`, `team_size INTEGER`).
- **Startup segments** (`seed`, `series_a`, `series_b`) are polled at `priority_min_interval_minutes` regardless of tier, sort right after priority boards in `companies_due`, and are never deferred by the 800-board cap. This does not change their tier: Tier 1 is still only set by the human.

```python
@dataclass(frozen=True)
class Company:
    name: str
    ats: str
    slug: str
    tier: int
    @property
    def key(self) -> str: return f"{self.ats}:{self.slug}"
```

### B3.2 `Job` (`src/models.py`)

```python
@dataclass
class Job:
    job_id: str            # f"{ats}:{slug}:{native_id}"  (native_id as str)
    company_key: str       # Company.key
    company: str           # display name
    ats: str
    title: str
    location: str          # raw string, "" if unknown
    url: str               # direct apply/view link
    description: str       # PLAIN TEXT (HTML already stripped), "" if unknown
    posted_at: str | None  # ISO UTC "Z" or None
    salary: str | None
    remote: bool | None    # None if unknown
```

Fields computed by the filter (stored in DB, not produced by adapters): `country`, `min_exp`, `max_exp`, `exp_signal`, `matched`, `reject_reason`.

### B3.3 SQLite schema (`data/jobs.db`). Use exactly this DDL

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS companies (
  company_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ats TEXT NOT NULL,
  slug TEXT NOT NULL,
  tier INTEGER NOT NULL,          -- base tier from companies.csv
  auto_tier INTEGER,              -- NULL normally; 2 when a Tier 3 company has an open matched job
  first_crawled_at TEXT,          -- NULL until first successful crawl
  last_crawled_at TEXT,
  last_error TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  consecutive_404 INTEGER NOT NULL DEFAULT 0,
  empty_streak INTEGER NOT NULL DEFAULT 0,
  disabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  company_key TEXT NOT NULL,
  company TEXT NOT NULL,
  ats TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  country TEXT,
  remote INTEGER,
  url TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  posted_at TEXT,
  salary TEXT,
  min_exp REAL,
  max_exp REAL,
  exp_signal TEXT,
  matched INTEGER NOT NULL DEFAULT 0,
  reject_reason TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
  closed_at TEXT,
  miss_count INTEGER NOT NULL DEFAULT 0,
  alerted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_key, status);
CREATE INDEX IF NOT EXISTS idx_jobs_matched ON jobs(matched, status, first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_alert ON jobs(matched, alerted);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

Job descriptions remain available as plain UTF-8 text in SQLite. When opening a database from the older zlib-compressed format, `Store` migrates those description values to plain text. The whole database is compressed with xz for the release asset.

## B4. Config (`config/config.yaml`). Create with exactly these defaults

```yaml
filters:
  roles_include:
    - associate software engineer
    - associate engineer
    - associate developer
    - swe
    - software engineer
    - software engineering
    - software developer
    - software development engineer
    - sde
    - developer
    - engineering intern
    - ml
    - machine learning
    - data science
    - data scientist
    - full stack
    - fullstack
    - full-stack
    - backend
    - back-end
    - back end
    - backend engineer
    - back-end engineer
    - back end engineer
    - backend developer
    - infrastructure engineer
    - reliability engineer
    - frontend
    - front-end
    - front end
    - frontend engineer
    - front-end engineer
    - frontend developer
    - devops
    - security
    - qa automation
    - ai engineer
    - ml engineer
    - machine learning engineer
    - machine learning intern
    - data science intern
    - security engineer
    - ai/ml
    - research engineer
    - ai research
    - ml research
    - machine learning research
    - deep learning research
    - computer vision research
    - genai research
    - data engineer
    - python developer
    - graduate engineer trainee
  roles_exclude_title:
    - senior
    - sr
    - lead
    - principal
    - staff
    - manager
    - director
    - head
    - architect
    - vp
    - procurement
    - sales
    - marketing
    - recruit
    - recruiting
    - talent
    - hr
    - finance
    - legal
    - operations
    - founder
    - growth
    - business development
    - customer success
  entry_level_title_tokens:
    - associate
    - junior
    - jr
    - trainee
    - graduate
    - new grad
    - entry level
    - intern
    - sde-1
    - sde 1
    - sde1
  max_min_experience: 2          # keep jobs whose minimum required years <= this
  keep_unknown_experience: true  # keep jobs with no experience info (flagged "unknown")
  target_grad_years: [2027]
  allow_unspecified_grad_year: true
  require_title_any: [intern, interns, internship, internships]
  countries: [India]             # allowed countries; [] means allow all
  include_remote_unspecified: false  # location exactly "Remote" with no country

polling:
  tier1_min_interval_minutes: 15
  tier2_min_interval_minutes: 60
  tier3_min_interval_minutes: 1440
  priority_min_interval_minutes: 15
  concurrency: 30
  timeout_seconds: 15
  retries: 3
  user_agent: "JobRadar/1.0 (personal job search)"

alerts:
  email_enabled: true
  max_jobs_per_email: 100
  daily_digest_hour_ist: 8       # attach jobs.xlsx once per day at/after this IST hour
  ntfy_topic: ""                 # optional; empty disables
  repeat_suppression_days: 120   # never re-alert the same opening within this window
  dismissed_path: config/dismissed.txt

export:
  excel_path: data/jobs.xlsx

limits:
  disable_after_consecutive_404: 5
  close_after_missed_cycles: 2
  empty_streak_before_close: 3
```

`src/config.py` loads this file, merges over built-in defaults (same values), and exposes a typed object. Missing keys fall back to defaults. Invalid YAML → clear error and exit code 2.

## B5. `src/textutil.py`

```python
def html_to_text(s: str | None) -> str
```
Steps in order: `None`→`""`; `html.unescape` **first** (Greenhouse `content` is HTML-escaped), parse with BeautifulSoup (`"html.parser"`), `get_text(" ")`, collapse whitespace to single spaces, strip.

```python
def now_utc_iso() -> str      # "2026-10-12T04:30:00Z" (seconds precision)
def epoch_ms_to_iso(ms) -> str | None
def normalize_iso(s: str | None) -> str | None   # any ISO string with offset → UTC "Z"; None/invalid → None
```

## B6. HTTP fetcher (`src/fetcher.py`)

- One shared `aiohttp.ClientSession` per run with header `User-Agent` from config.
- `asyncio.Semaphore(concurrency)` limits in-flight requests.
- Total timeout per request: `timeout_seconds`.
- `async def get_json(session, url, *, method="GET", json_body=None) -> Any`
- Retry up to `retries` times on: timeouts, connection errors, HTTP 429, HTTP 5xx. Backoff `1s, 2s, 4s` plus random jitter 0-0.5 s. If `Retry-After` is present on 429, wait that many seconds (cap 30).
- HTTP 404 → raise `NotFoundError` immediately (no retry).
- Other 4xx → raise `FetchError`.
- Invalid JSON → raise `FetchError`.
- Define `class FetchError(Exception)` and `class NotFoundError(FetchError)`.

## B7. Adapters (`src/adapters/`)

### B7.1 Interface (`base.py`)

```python
class Adapter(Protocol):
    ats: str
    async def fetch(self, session, company: Company) -> list[Job]: ...
    def parse(self, raw: Any, company: Company) -> list[Job]: ...   # PURE, no network
```
`fetch` = build URL → `get_json` → `parse`. All tests target `parse`.

Rules for every `parse`:
- Skip (don't crash on) any single malformed job entry; log a warning.
- `job_id = f"{ats}:{slug}:{native_id}"`.
- `description` is plain text via `html_to_text`.
- `posted_at` via `normalize_iso` / `epoch_ms_to_iso`.
- Empty/missing title or URL → skip the entry.

### B7.2 Endpoints and expected fields (**VERIFY LIVE IN PHASE 1**)

| ATS | Request | Expected response → field mapping |
|---|---|---|
| **Greenhouse** | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | `jobs[]`: `id`→native_id, `title`, `absolute_url`→url, `location.name`→location, `content` (HTML-escaped)→description, `first_published` if present else `updated_at`→posted_at |
| **Lever** | `GET https://api.lever.co/v0/postings/{slug}?mode=json` | Response is a **list**: `id`→native_id, `text`→title, `hostedUrl`→url, `categories.location`→location, `descriptionPlain` (fallback `description` via `html_to_text`; also append text of `lists[]` if present)→description, `createdAt` (epoch ms)→posted_at, `workplaceType=="remote"`→remote, `salaryRange` (if present) → salary text like `"INR 800000-1200000 / year"` |
| **Ashby** | `GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` | `jobs[]`: `id`→native_id, `title`, `jobUrl`→url, `location`→location, `descriptionPlain` (fallback `descriptionHtml` via `html_to_text`)→description, `publishedAt`→posted_at, `isRemote`→remote, skip entries where `isListed` is `false`, compensation summary if present→salary |
| **Recruitee** | `GET https://{slug}.recruitee.com/` | Verified public boards server-render job anchors at `/o/{job-slug}` with title and location/workplace metadata in HTML; listing pages may omit description, posted date, and salary |
| **BambooHR** | `GET https://{slug}.bamboohr.com/careers/list` | Verified JSON response has `result[]` with `id`, `jobOpeningName`, `location`, `atsLocation`, and optional `isRemote`; public listing may omit description, posting date, and compensation |
| **Breezy HR** | `GET https://{slug}.breezy.hr/` | Verified public board server-renders jobs under `/p/{job-id}` with title in a heading and location in `li.location`; listing omits description, posted date, and salary |

If a live response differs from this table, **trust the live response**, fix the adapter, and list the differences in your Phase 1 report.

## B8. Filters (`src/filters.py`). The most important module

All functions are pure.

### B8.1 Public API

```python
@dataclass
class FilterResult:
    matched: bool
    reject_reason: str | None     # e.g. "title_excluded", "role_not_included", "experience_too_high", "country_not_allowed"
    country: str | None
    min_exp: float | None
    max_exp: float | None
    exp_signal: str               # "fresher_keyword" | "range" | "plus" | "at_least" | "plain" | "up_to" | "title_entry" | "unknown"

def evaluate(job: Job, cfg: FilterConfig) -> FilterResult
def parse_experience(title: str, description: str) -> tuple[float | None, float | None, str]
def detect_country(location: str) -> str | None
```

### B8.2 `evaluate` order (stop at first rejection)

1. `title_l = job.title.lower()`.
2. **Excluded title:** if any token in `roles_exclude_title` matches as a whole word/phrase (regex `\b<token>\b`; for `sr` also match `sr.`) **or** title matches `\bsde[- ]?(2|3|4)\b` **or** `\b(engineer|developer)\s+(ii|iii|iv)\b` or `\b(ii|iii|iv)\b$` → reject `title_excluded`.
3. **Required title:** if `require_title_any` is non-empty and no token matches as a whole word/phrase in `title_l` → reject `title_required_missing`.
4. **Role included:** at least one token from `roles_include` must appear as a whole word/phrase in `title_l`. If none → reject `role_not_included`.
5. **Experience:** call `parse_experience`. Internship titles are treated as entry-level (`min_exp=0`, signal `title_entry`) before inspecting the description. Otherwise, if `min_exp is not None and min_exp > max_min_experience` → reject `experience_too_high`. If `min_exp is None` and `keep_unknown_experience` is false → reject `experience_unknown`.
6. **Country:** `detect_country(job.location)`. If `countries` non-empty and the detected country not in it → reject `country_not_allowed`. Special case: if location lowercased stripped equals `"remote"` (no country) → allowed only if `include_remote_unspecified`. If location is empty or country is `None` and not remote-only → reject `country_unknown`.
7. **Graduation year:** after the other checks pass, if `target_grad_years` is non-empty and detected years do not overlap the targets → reject `grad_year_mismatch`; if no years are detected and `allow_unspecified_grad_year` is false → reject `grad_year_unknown`.
8. Otherwise `matched = True`.

Even rejected jobs get their `country`, `min_exp`, `max_exp`, `exp_signal` saved, for debugging.

### B8.3 `parse_experience(title, description)`

Text = `(title + "\n" + description).lower()`.

Collect all candidate minimums from these regexes (compile with `re.IGNORECASE`):

| Name | Regex | min / max |
|---|---|---|
| `fresher_keyword` | `\b(freshers?\|new grads?\|recent graduates?\|entry[- ]level\|campus hire\|graduate trainee)\b` | min = 0 |
| `range` | `(\d+(?:\.\d+)?)\s*(?:-\|–\|—\|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?\|yrs?)` | min = group1, max = group2 |
| `up_to` | `(?:up\s*to\|upto\|less than)\s*(\d+(?:\.\d+)?)\s*(?:years?\|yrs?)` | min = 0, max = group1 |
| `plus` | `(\d+(?:\.\d+)?)\s*\+\s*(?:years?\|yrs?)` | min = group1 |
| `at_least` | `(?:minimum\|min\.?\|at least)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:years?\|yrs?)` | min = group1 |
| `at_least` | `(\d+(?:\.\d+)?)\s*(?:years?\|yrs?)\s+or\s+more` | min = group1 |
| `plain` | `(\d+(?:\.\d+)?)\s*(?:years?\|yrs?)['’]?\s*(?:of\s*)?(?:relevant\s*\|professional\s*\|hands-on\s*\|prior\s*\|work\s*\|industry\s*)*(?:experience\|exp\b)` | min = group1 |

Resolution rules:
- If the title contains `intern`, `interns`, `internship`, or `internships` as a whole word, return `(0.0, None, "title_entry")` before parsing the description.
- **`min_exp` = the SMALLEST minimum found** among all candidates. (Reason: descriptions often say "0-2 years; 5+ years AWS preferred". Falsely rejecting a real fresher role costs more than falsely keeping a senior one.)
- `max_exp` = the smallest max found among `range`/`up_to` candidates, else `None`.
- `exp_signal` = name of the regex that produced the smallest minimum (prefer `fresher_keyword` on ties).
- If **no candidates**: look at `title`. If any `entry_level_title_tokens` matches as a whole word/phrase → `(0.0, None, "title_entry")`. Else → `(None, None, "unknown")`.
- Ignore numbers ≥ 40 as experience (they're not years, e.g. "50 years of history").

### B8.4 `detect_country(location)`

Lowercase the string. Return `"India"` if it contains the word `india` or any of: `bengaluru, bangalore, hyderabad, pune, chennai, mumbai, navi mumbai, delhi, new delhi, gurgaon, gurugram, noida, greater noida, kolkata, ahmedabad, kochi, cochin, coimbatore, jaipur, indore, chandigarh, mohali, thiruvananthapuram, trivandrum, nagpur, bhubaneswar, vadodara, surat, lucknow, mysuru, mysore, karnataka, telangana, maharashtra, tamil nadu, haryana, uttar pradesh, delhi ncr`.
Return `"United States"` if it contains `united states`, `usa`, `u.s.`, `, us`, or ends with `, us`, or contains a US state abbreviation pattern like `, ca` / `, ny` / `, tx` / `, wa` as a **whole token after a comma** (use a full list of 50 state abbreviations), or `san francisco`, `new york`, `seattle`, `austin`, `boston`, `chicago`, `indianapolis`, or `indiana`.
For the ambiguous `, in` suffix, prefer India's ISO code unless a recognizable US city, `Indiana`, or an explicit US marker identifies the location as US.
Return `"United Kingdom"` for `united kingdom`, `uk`, `london`; `"Canada"` for `canada`, `toronto`, `vancouver`; `"Germany"`, `"Singapore"`, `"Australia"` similarly with the country name and one main city each.
Otherwise `None`.
(Only India is needed for default behaviour; others can be extended later.)

### B8.5 Required test cases (`tests/test_filters.py`). Every row must pass

Default config. "Loc" is the location string. "Result" = `matched` / `reject_reason or min_exp`.

| # | Title | Description | Loc | Expected |
|---|---|---|---|---|
| 1 | Associate Software Engineer | "" | Bengaluru, India | matched; min_exp 0; signal `title_entry` |
| 2 | Senior Software Engineer | "3 years experience" | Pune, India | rejected `title_excluded` |
| 3 | Software Engineer | "0-2 years of experience" | Hyderabad, India | matched; min 0; max 2; signal `range` |
| 4 | Software Engineer | "3-5 years of experience" | Mumbai, India | rejected `experience_too_high` |
| 5 | Backend Engineer | "2+ years of experience in Python" | Chennai, India | matched; min 2 |
| 6 | Backend Engineer | "3+ years of experience" | Noida, India | rejected `experience_too_high` |
| 7 | Full Stack Developer | "Freshers can apply" | Pune, India | matched; min 0; signal `fresher_keyword` |
| 8 | Full Stack Developer | "We build great products." | Pune, India | matched; min None; signal `unknown` |
| 9 | AI Engineer | "Minimum 1 year of experience" | Bengaluru, India | matched; min 1; signal `at_least` |
| 10 | Software Engineer II | "" | Bengaluru, India | rejected `title_excluded` |
| 11 | Associate Product Manager | "" | Bengaluru, India | rejected `title_excluded` (contains "manager") |
| 12 | Software Engineer | "0-2 years. Preferred: 5+ years AWS." | Pune, India | matched; min 0 |
| 13 | Graduate Engineer Trainee | "" | Chennai, India | matched; min 0; signal `title_entry` |
| 14 | Data Engineer | "Up to 2 years of experience" | Hyderabad, India | matched; min 0; max 2; signal `up_to` |
| 15 | Machine Learning Engineer | "5 years of experience required" | Bengaluru, India | rejected `experience_too_high` |
| 16 | Business Development Associate | "" | Mumbai, India | rejected `role_not_included` |
| 17 | Staff Software Engineer | "" | Pune, India | rejected `title_excluded` |
| 18 | SDE-1 | "" | Bengaluru, India | matched; min 0; signal `title_entry` |
| 19 | SDE-2 | "" | Bengaluru, India | rejected `title_excluded` |
| 20 | Software Engineer | "0-2 years" | San Francisco, CA | rejected `country_not_allowed` |
| 21 | Software Engineer | "0-2 years" | Remote | rejected `country_unknown` (default config) |
| 22 | Software Engineer | "0-2 years" | Remote - India | matched |
| 23 | Software Engineer Intern | "" | Pune, India | rejected `title_excluded` (default config) |
| 24 | Software Engineer | "Our company has 50 years of history." | Pune, India | matched; min None; signal `unknown` |
| 25 | Software Procurement Intern | "" | Bengaluru, India | rejected `title_excluded` (runtime config; exclusions run before role inclusion) |
| 26 | Software Engineer Intern | "" | Remote, IN | country detected as India |
| 27 | Research Intern | "" | Bengaluru, India | rejected `role_not_included` (runtime config; only technical research titles are included) |

If any case fails because the spec text is wrong or inconsistent, tell the human which case and why. Do not silently change a test.

## B9. Store (`src/store.py`)

```python
class Store:
    def __init__(self, path: str)               # opens DB, runs DDL, row_factory=sqlite3.Row
    def sync_companies(self, companies: list[Company]) -> None   # upsert rows; do NOT reset crawl stats
    def companies_due(self, tier2_min_interval_minutes: int, tier3_min_interval_minutes: int, now: str, only_tier: int | None, only_slug: str | None, limit: int | None, tier1_min_interval_minutes: int = 15, priority_min_interval_minutes: int = 15) -> list[Company]
    def apply_crawl(self, company: Company, jobs_with_results: list[tuple[Job, FilterResult]], now: str) -> CrawlDiff
    def record_error(self, company: Company, err: Exception, now: str) -> None
    def pending_alerts(self, limit: int) -> list[sqlite3.Row]   # matched=1, alerted=0, status='open', ORDER BY first_seen DESC
    def mark_alerted(self, job_ids: list[str]) -> None
    def prune_closed_jobs(self, now: str, retention_days: int = 45) -> int
    def get_meta(self, key) -> str | None
    def set_meta(self, key, value) -> None
    def stats(self) -> dict
```

### B9.1 `companies_due`
Let `effective_tier = COALESCE(auto_tier, tier)`. Return companies where `disabled = 0` AND any of:
- `last_crawled_at IS NULL` (never crawled, any tier)
- `priority_board = 1` AND the last crawl is at least `priority_min_interval_minutes` ago
- `priority_board = 0 AND effective_tier = 1` AND the last crawl is at least `tier1_min_interval_minutes` ago
- `priority_board = 0 AND effective_tier = 2` AND the last crawl is at least `tier2_min_interval_minutes` ago
- `priority_board = 0 AND effective_tier = 3` AND the last crawl is at least `tier3_min_interval_minutes` ago

Apply `only_tier` (matches `effective_tier`), `only_slug`, `limit` after that. Order never-crawled companies last so a big merge of new companies cannot starve Tier 1.

`next_check` is persisted per company and is authoritative when set. After a successful crawl or failure, schedule the next check at the interval for the base tier, except that a priority board uses `priority_min_interval_minutes`. A company becomes a priority board after any matching job and remains priority. A never-crawled board is due immediately.

If more than 800 companies are due in one run, crawl Tier 1 and 2 first and defer the rest to the next run (log how many were deferred). This keeps a run inside the 14-minute workflow timeout. Each run stops starting work after an 11-minute fetch budget, cancels unfinished requests, logs those boards as skipped, and does not mark skipped boards as failed or close their jobs. One adapter's exception is recorded for that board and does not stop other boards.

### B9.2 `apply_crawl`. **Exact algorithm** (single transaction per company)

Input: the fully-parsed, filter-evaluated jobs for one company from one **successful** fetch.

```
is_first_crawl = (company.first_crawled_at IS NULL)

known = {job_id: (status) for existing rows of this company_key}
seen_ids = {job.job_id for job in jobs}

for (job, result) in jobs:
    if job_id NOT in known:
        INSERT row with first_seen=now, last_seen=now, status='open', miss_count=0,
             alerted = 1 if is_first_crawl or an open cross-ATS duplicate exists else 0,
             plus filter result columns
        diff.new.append(job_id); if matched and not is_first_crawl and no open cross-ATS duplicate: diff.new_matched.append(job_id)
    else:
        UPDATE description/title/location/url/salary/filter columns, last_seen=now, miss_count=0
        if status == 'closed': UPDATE status='open', closed_at=NULL   (reopened: do NOT alert)

open_before = {job_id for rows where status='open'}
missing = open_before - seen_ids

if len(jobs) == 0 and len(open_before) > 0:
    empty_streak += 1
    if empty_streak >= empty_streak_before_close: close all missing
    # else: do nothing (a sudden empty board is suspicious)
else:
    empty_streak = 0
    for each job_id in missing:
        miss_count += 1
        if miss_count >= close_after_missed_cycles: status='closed', closed_at=now

UPDATE companies SET first_crawled_at = COALESCE(first_crawled_at, now), last_crawled_at=now,
       next_check=<scheduled UTC timestamp>, priority_board=<sticky if any matched job>,
       last_error=NULL, consecutive_errors=0, consecutive_404=0, empty_streak=<computed>
```
`CrawlDiff` has: `new`, `new_matched`, `closed`, `reopened` (lists of job_ids).

Descriptions are stored as plain UTF-8 text. Each job also has a canonical key made from normalized company, title, and location. The key is for cross-source duplicate detection only; the original ATS job rows remain stored. A newly discovered duplicate from another ATS is marked alerted without sending a second alert. `pending_alerts` selects one pending representative across ATS sources, and marking it alerted marks its cross-source counterparts alerted. Multiple records from the same ATS are not deduplicated.

At the end of a successful non-dry-run cycle, delete jobs that have been closed for more than 45 days and run `VACUUM`. Keep all open jobs and recently closed jobs.

**Auto-tier rule (same transaction, after the job updates):** count this company's rows with `matched=1 AND status='open'`. If the company's base `tier = 3` and the count is `> 0` → `auto_tier = 2`. Otherwise → `auto_tier = NULL`. Companies with base tier 1 or 2 are never changed by this rule.

### B9.3 `record_error`
- Set `last_error` (truncate to 300 chars), `consecutive_errors += 1`.
- If error is `NotFoundError`: `consecutive_404 += 1`; if `>= disable_after_consecutive_404` → `disabled = 1`.
- Else: `consecutive_404 = 0`.
- Set `next_check` using the applicable polling interval.
- **Never** touch the company's jobs on error (no closing).

### B9.4 Required tests (`tests/test_store.py`, in-memory or temp-file DB)
1. First crawl of a company inserts jobs with `alerted=1` → `pending_alerts()` returns nothing.
2. Second crawl with one extra matched job → exactly that job is pending.
3. A job missing for 1 cycle stays `open`; missing for 2 cycles → `closed`.
4. A closed job that reappears becomes `open`, is **not** pending, and `first_seen` is unchanged.
5. A fetch returning 0 jobs when 5 were open does **not** close them on the 1st and 2nd occurrence, closes them on the 3rd.
6. `record_error` never changes any job's status.
7. Five consecutive `NotFoundError` → `disabled=1`.
8. `companies_due`: never-crawled boards are due; base Tier 1 is due every 15 minutes, Tier 2 every 60 minutes, Tier 3 daily, and priority boards every 15 minutes.
9. `next_check` persists the next due time through success/failure, and skipped boards remain due.
10. A Tier 3 company whose crawl returns a matched job gets `auto_tier = 2` and a sticky priority flag; when that job closes (and no other matched open job remains) `auto_tier` returns to `NULL`.
11. A company with 0 jobs is stored and stays enabled (it is not an error and is never deleted).
12. Cross-source duplicates share a canonical key; only one is alerted/exported across ATS sources while same-source records remain separate.

### B9.5 Alert ledger (Phase 10)
- Each job stores `fingerprint = normalized company | normalized title`, where years, seasons, durations, work-mode words, and words from the job's own location (plus major Indian city names) are removed from the title. Reposts, multi-city listings, and the same opening on another ATS share a fingerprint.
- Table `alert_log(fingerprint PRIMARY KEY, job_id, company, title, url, alerted_at)` records every fingerprint sent by instant alert or digest. `mark_alerted(job_ids, now)` writes it. It is never pruned with closed jobs.
- `suppress_repeat_alerts(now, window_days, dismissed)` runs before `pending_alerts` and marks `alerted=1` on pending matches whose fingerprint was sent within `repeat_suppression_days`, or whose job ID / URL / fingerprint is in `config/dismissed.txt`.
- Within one email, same-fingerprint rows are not collapsed (existing same-source rule in B9.2 holds).
- On first open after upgrade, every `matched=1 AND alerted=1` job is copied into `alert_log` once (`meta.alert_log_backfilled`).
- The crawl workflow saves state with `if: always()` (unless the restore failed) so alerts sent before a later failure stay recorded. Fetch budget 7 minutes; job timeout 20 minutes; state compressed with `xz -6`.

## B10. Notifications (`src/notify.py`)

```python
def build_email(rows: list[sqlite3.Row], now_utc: str) -> tuple[str, str, str]   # (subject, text_body, html_body)  PURE
def send_email(subject, text, html, attachments: list[tuple[str, bytes]] = []) -> None   # reads env vars
def send_ntfy(topic: str, title: str, message: str) -> None   # simple POST to https://ntfy.sh/<topic>
```

- Env vars: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`. If any is missing → raise a clear `ConfigError` (do not print values).
- `smtplib.SMTP_SSL("smtp.gmail.com", 465)`, `login`, `send_message`. Use `email.message.EmailMessage` with plain text + HTML alternative.
- **Subject:** `[New Job] {N} new matches: {Company1}, {Company2}, {Company3}…` (max 3 company names, then `…`).
- **HTML body:** a table with columns `Role | Company | Stage | Location | Exp | Batch year | Posted | Apply` where Apply is a clickable link. `Stage` shows the company segment and team size (e.g. `Seed · 25 ppl`), blank when unknown. Show detected graduation years in `Batch year`, or `Not specified` if none were parsed. Sort startup-first by segment (B3.1a), then newest first. Show `Exp` as `0-2`, `2+`, or `?` (unknown). Show times in IST.
- Cap rows at `max_jobs_per_email`. Rows beyond the cap stay `alerted=0` and go out next cycle.
- HTML-escape every field (job titles come from the internet).
- `mark_alerted` is called **only after** `send_email` succeeds. On failure: log the error, leave `alerted=0`, continue (the next cycle retries).

`tests/test_notify.py`: test `build_email` with 3 fake rows (subject format, HTML escaping of `<script>` in a title, cap behaviour). No SMTP calls in tests.

## B11. Excel export (`src/export.py`)

`export_excel(store, path)` writes with pandas + openpyxl:

| Sheet | Rows | Columns |
|---|---|---|
| `Matches` | `matched=1 AND status='open'`, newest `first_seen` first | Role, Company, Location, Country, Min Exp, Max Exp, Exp Signal, Posted, First Seen (IST), Salary, Source, Link |
| `All Open` | `status='open'` | same columns + Matched, Reject Reason |
| `Stats` | one block | companies total/disabled/errored, open jobs, matched jobs, new in last 24h, last run time |

Formatting: frozen header row, autofilter on, column widths set sensibly (title 45, company 25, link 60), `Link` cells are hyperlinks. Write to a temp file then rename (atomic).

## B12. CLI (`src/main.py`)

```
python -m src.main run [--dry-run] [--no-email] [--tier {1,2,3}] [--company SLUG] [--limit N]
python -m src.main validate            # validate config.yaml and companies.csv, print summary, exit 0/2
python -m src.main discover --input FILE [--input FILE ...] [--rps 2] [--merge]    # Phase 7
python -m src.main discover-hn          # fetch latest HN hiring thread into config/inputs/
python -m src.main discover-yc          # India-region YC companies -> config/inputs/yc_india.csv + company_meta.csv
python -m src.main discover-funding     # recently funded startups from Entrackr/Inc42 RSS -> config/inputs/funding_news.csv
python -m src.main stats               # print DB stats
```

`run` flow, in this exact order:
1. Load config; load + validate companies; `store.sync_companies`.
2. `due = store.companies_due(...)`.
3. Create one `aiohttp` session; for each due company run `adapter.fetch` concurrently (`asyncio.gather` with `return_exceptions=True`, concurrency already bounded by the semaphore).
4. For each result: on exception → `store.record_error`; on success → evaluate filters on every job, then `store.apply_crawl`.
5. Unless `--dry-run`: prune jobs closed more than 45 days ago and run `VACUUM`.
6. Unless `--dry-run`: `export_excel`.
7. Unless `--no-email` or `--dry-run`: fetch `pending_alerts(max_jobs_per_email)`; if any → `send_email`; on success → `mark_alerted`; optionally `send_ntfy`.
8. **Daily digest:** if `now_ist.hour >= daily_digest_hour_ist` and `meta.last_digest_date != today_ist` → send an email with `jobs.xlsx` attached (subject `[JobRadar] Daily digest: {N} new, {M} open matches`). The body lists only `digest_candidates` (open matches never sent before, e.g. silently seeded boards); earlier matches appear as a count only. On success, `mark_alerted` the listed jobs and set `meta.last_digest_date`.
9. Print ONE summary line: `run ok | companies=<n> ok=<n> errors=<n> | jobs_seen=<n> new=<n> new_matched=<n> closed=<n> | emails=<0/1> | secs=<n>`.
10. Exit code: `0` normally (even if some companies failed); `1` only on a crash outside per-company handling; `2` on config errors.

`--dry-run`: fetch and evaluate, **write nothing** to the DB, send nothing, print what would be new. (Implement by running `apply_crawl` inside a transaction that is rolled back.)

Logging: use the `logging` module to stdout, format `%(asctime)s %(levelname)s %(message)s`. Log each company failure as one WARNING line. Never log secrets or full descriptions. The workflow logs the xz-compressed state asset size and emits a warning if it exceeds 300 MiB.

## B13. GitHub Actions (`.github/workflows/crawl.yml`)

```yaml
name: crawl
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:

concurrency:
  group: crawl
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 14
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Restore crawler state from release
        id: restore-state
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          mkdir -p data
          releases="$(gh release list --limit 1000 --json tagName --jq '.[].tagName')"
          if printf '%s\n' "$releases" | grep -Fxq state; then
            gh release download state --pattern 'jobs.db.xz' --dir data --clobber
            xz -t data/jobs.db.xz
            xz -dc data/jobs.db.xz > data/jobs.db
            rm data/jobs.db.xz
            echo "found=true" >> "$GITHUB_OUTPUT"
          else
            echo "found=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Run crawler
        run: |
          if [ "${{ steps.restore-state.outputs.found }}" = "true" ]; then
            python -m src.main run
          else
            python -m src.main run --no-email
          fi
        env:
          GMAIL_USER: ${{ secrets.GMAIL_USER }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          ALERT_TO: ${{ secrets.ALERT_TO }}

      - name: Compress and report state size
        run: |
          xz -T0 -9 -c data/jobs.db > data/jobs.db.xz
          python - <<'PY'
          from pathlib import Path

          database_size = Path("data/jobs.db").stat().st_size
          asset_size = Path("data/jobs.db.xz").stat().st_size
          print(f"State database: {database_size / 1048576:.2f} MiB")
          print(f"Compressed state asset: {asset_size / 1048576:.2f} MiB")
          if asset_size > 300 * 1024 * 1024:
              print("::warning::Compressed state asset exceeds 300 MiB.")
          PY

      - name: Save state as release asset
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          releases="$(gh release list --limit 1000 --json tagName --jq '.[].tagName')"
          if ! printf '%s\n' "$releases" | grep -Fxq state; then
            gh release create state \
              --target "$GITHUB_SHA" \
              --title "JobRadar state" \
              --notes "Latest compressed crawler database. Managed by the crawl workflow."
          fi
          gh release upload state data/jobs.db.xz --clobber
          gh release upload state data/jobs.xlsx --clobber
```

Notes for Claude Code to relay to the human:
- The first workflow run creates the `state` release and suppresses email while seeding initial company data.
- GitHub may delay scheduled runs by minutes, and may skip some under load. That is expected.
- In public repos GitHub disables scheduled workflows after ~60 days of repo inactivity. Keep the repo **private**.
- The latest `jobs.db.xz` database asset and `jobs.xlsx` workbook are downloadable from the `state` release on github.com. The workflow logs both uncompressed and compressed database sizes.
- Keep the old `state` branch until the release-asset workflow has completed successfully a couple of times; the branch is no longer used for persistence.
- Free-tier minutes are limited on private repos; if the monthly quota is hit, reduce the cron frequency to every 30 min.

## B14. Out of scope (do not build unless the human explicitly asks)

Application tracker inside the program, web dashboard, LinkedIn/Naukri/Indeed scraping, auto-apply bots, resume scoring, Workday/Workable/SmartRecruiters/Zoho adapters (Phase 8 only), custom-page/sitemap/aggregator sources (Phase 9 only), Docker, databases other than SQLite.

---

# PART C: PHASES AND ACCEPTANCE CHECKS

After every phase: run `pytest -q`, print results, summarize what changed, **STOP**.

### Phase 0: Skeleton
Build: repo layout (B2), `requirements.txt`, `.gitignore`, `.env.example`, empty modules with docstrings, `config.py`, `models.py`, `textutil.py`, `registry.py` (CSV loader with validation per B3.1), `config/config.yaml`, a sample `config/companies.csv` with a `#` comment line and 3 rows.
Checks:
- `python -m src.main validate` prints `config ok, companies: 3` and exits 0.
- Corrupt a CSV row temporarily → `validate` exits 2 with a clear message (then restore).
- `pytest -q` passes `test_textutil.py` (HTML-escaped Greenhouse-style input → clean text; date conversion cases).

### Phase 1: Verify endpoints + three adapters
Build: `scripts/probe_endpoints.py` (live; takes one slug per ATS as CLI args; saves the first ~5 jobs of each response to `tests/fixtures/{ats}_sample.json`; prints the top-level keys and one sample job's keys). Then `fetcher.py`, `adapters/*`, `tests/test_adapters.py`.
Starting slugs to try (**unverified, if any 404, find a real one from a company careers page**): greenhouse `stripe`, lever `palantir`, ashby `ramp`.
Checks:
- Probe script runs and saves 3 fixtures. **Report any field that differs from B7.2.**
- `test_adapters.py`: for each ATS, `parse(fixture)` returns ≥1 Job, every Job has non-empty `job_id`, `title`, `url`; `description` contains no `<` or `&lt;`; a deliberately malformed entry is skipped without raising.
- `scripts/smoke_live.py` fetches the 3 live slugs through the real `fetch()` path and prints job counts.

### Phase 2: Store + diff
Build: `store.py` per B9. Checks: all 8 tests in B9.4 pass.

### Phase 3: Filters
Build: `filters.py` per B8. Checks: all 24 cases in B8.5 pass. Then run the filters over the real fixtures and print a table of 20 jobs with `matched` / `reject_reason` so the human can eyeball them. (Human task A7.)

### Phase 4: Wire `run` (no email, no Excel yet)
Build: `main.py` flow steps 1-4, 8, 9, `--dry-run`, `stats`.
Checks:
- `python -m src.main run --dry-run --limit 3` prints the summary line and writes nothing (verify DB file unchanged).
- `python -m src.main run --limit 3` twice: first run `new>0 new_matched=0` (silent seed), second run `new=0`.
- Kill the network (or use a bad slug) → run still exits 0 with `errors>=1`.

### Phase 5: Email + Excel
Build: `notify.py`, `export.py`, flow steps 5-7. Human completes A3 first and puts credentials in a local `.env` (load with `os.environ`; do not add a dotenv dependency, just tell the human to `export` the variables or use `set -a; source .env; set +a`).
Checks:
- `pytest -q` passes `test_notify.py`.
- To test email safely: add `python -m src.main test-email` that sends one dummy 2-row email. Human confirms receipt.
- `jobs.xlsx` opens, has 3 sheets, links are clickable.
- Simulate a new matched job (insert a company, then delete one of its jobs from the DB, then run) → exactly 1 alert email, and a second run sends none.

### Phase 6: GitHub Actions
Build: workflow (B13). Human completes A5. Push to GitHub, trigger `workflow_dispatch`.
Checks:
- First run succeeds, sends no email while silently seeding, creates the `state` release with `jobs.db.xz`, and logs the compressed asset size.
- A second run (after 15 min or manual trigger) shows `new=0` for unchanged companies, proving state persisted.
- Failure test: temporarily break one slug → run still green, error recorded in `companies.last_error`.

### Phase 7: Company discovery + scale (keep ALL hits)
Build `discovery.py`, `scripts/discover_ats.py`, and the `discover` command. **Keep every company that has a valid board, even with zero jobs today** (it may hire later). Zero-job and no-India-job companies go to Tier 3.

**Inputs** (`--input FILE`, repeatable; also read all `config/seed_company_names*.txt` files and everything in `config/inputs/` by default):
- `.txt`: one company name per line; `#` comments and blank lines ignored.
- `.csv`: header must contain `name`; optional `website` (domain or URL). Other columns ignored.
- The human has two existing company databases; they convert each to CSV as described in A6.

**Normalization (for matching and dedupe only; never change the display name):** lowercase; strip punctuation; drop trailing words `inc, llc, ltd, limited, pvt, private, corp, corporation, co, technologies, technology, labs, software`. Dedupe across all inputs by normalized name, and by domain if present.

**Step 1: slug probing.** For each company generate up to **4** slug candidates, in this order, de-duplicated:
1. normalized name with no spaces (`acmecorp`)
2. hyphenated (`acme-corp`)
3. no-space name + `hq`
4. no-space name + `inc`
Do NOT use first-word-only slugs (too many false matches). Probe, for each of greenhouse / lever / ashby / workable / smartrecruiters, each candidate in order; stop probing that ATS at the first valid board. A company may hit more than one ATS; keep all hits and log them as `multi_ats`.
- Valid board = HTTP 200 and a parseable response (zero jobs is still valid).
- Use the matching adapter's `fetch` + `parse`; compute `job_count` and `india_job_count` (`detect_country(location) == "India"`).
- For Greenhouse also read the board name from `GET https://boards-api.greenhouse.io/v1/boards/{slug}` (field `name`) if available, and store it as `board_name`. Record `sample_url` (first job URL, or empty).
- If a board-name field is available, compare its normalized value with the input company name and reject a mismatch. Keep candidates from ATS responses that do not expose board identity for human review before merge.
- **Rate limit:** global maximum `--rps` requests/second (default 2, hard cap 5). Honor 429 `Retry-After`. At 2 rps, ~3,000 names can take several hours: this is expected. Run it locally, not on GitHub Actions.
- **Resumable:** keep `data/discover_progress.json` (set of `name|ats|slug` already probed). A rerun skips them. Write progress at least every 50 probes and on Ctrl-C.

**Step 2: careers-page detection** (only for rows with a `website`, and only if Step 1 found no valid board for that company):
- Try `https://{domain}/careers`, `/jobs`, `/about/careers`, `/company/careers`; stop at the first 200 response. Check `robots.txt` with `urllib.robotparser` and skip a path if disallowed. Max 1 request/second per host.
- Scan the HTML for supported ATS links using these regexes (case-insensitive):
  - Greenhouse: `(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)`
  - Lever: `jobs\.lever\.co/([a-z0-9_-]+)`
  - Ashby: `jobs\.ashbyhq\.com/([a-z0-9_.-]+)`
  - Workable: `apply\.workable\.com/([a-z0-9_-]+)`
  - SmartRecruiters: `jobs\.smartrecruiters\.com/([a-z0-9_-]+)`
  A detected slug is accepted only after it passes the same live validity check as Step 1.
- Unsupported ATS links (`myworkdayjobs.com`, `zohorecruit`) → append `name,ats,url` to `config/unsupported_ats_hits.csv` (feeds Phase 8).
- If the HTML contains `"@type":"JobPosting"` (any spacing/quoting variant) → append `name,url,signal` to `config/custom_pages.csv` with `signal=jsonld` (feeds Phase 9).

**Output:** `config/companies_candidates.csv` with columns `name,ats,slug,tier,job_count,india_job_count,board_name,sample_url,source`. `tier` = `2` if `india_job_count > 0`, else `3`. `source` ∈ `probe | careers_page`. **Tier 1 is never assigned by code; the human edits it by hand.**

**`--merge`:** appends candidate rows to `config/companies.csv` using only the columns `name,ats,slug,tier`; skips any `(ats, slug)` already present; first writes a backup `config/companies.csv.bak`; never edits existing rows. Running `--merge` twice adds nothing the second time.

Human step (A6): spot-check ~20 random rows of `companies_candidates.csv` (open `sample_url`, confirm it is the right company) **before** `--merge`. Name collisions are the main risk, since a slug can belong to a different company with the same name.

Checks:
- Run on a 10-name file containing 3 companies you know use these ATS; confirm they are found; names with special characters (`Cult.fit`, `L'Oreal`, `D. E. Shaw`) don't crash it.
- Interrupt with Ctrl-C mid-run and rerun: no probe is repeated (verify with a request counter in the log).
- A company with a valid board and 0 jobs appears in the output as tier 3.
- `--merge` twice: second run reports 0 added.
- After merging 100+ companies, `python -m src.main run` sends **no alert email** on its first crawl (silent seeding) and stays under the 14-minute limit by deferring excess companies (B9.1).

### Phase 8 (optional, only if asked): more ATS adapters
SmartRecruiters, Workable, Workday. For each: verify live first (as Phase 1), fixture, tests, then enable. Workday needs per-tenant `tenant`, `site`, and datacenter number `wdN`; extend `companies.csv` with an optional 5th column `extra` before doing this.

Use `config/unsupported_ats_hits.csv` (written by `discover`) as the starting company list for these adapters.

### Phase 9 (optional, only if asked): custom career pages and other sources
Do each sub-step separately and stop after each. For every one: verify live first, save fixtures, add offline tests. Requires the optional 5th CSV column `extra` in `companies.csv` (holds the page/sitemap URL). Make `registry.py` accept both 4-column and 5-column rows.

- **9a. `jsonld` adapter** (`ats=jsonld`, `extra` = careers listing URL): fetch the page, parse every `<script type="application/ld+json">` block (handle `@graph` and lists), keep objects with `@type` = `JobPosting`. Map: `title`, `url` (fallback to listing URL), `jobLocation.address` (`addressLocality`, `addressRegion`, `addressCountry`) → location, `datePosted` → posted_at, `description` via `html_to_text`, `baseSalary` → salary. `native_id` = `identifier.value` if present, else first 12 hex chars of `sha1(url)`. If the page has no JobPosting data, return `[]` and log once (this uses the normal empty-board safety rules). Candidates come from `config/custom_pages.csv`.
- **9b. `sitemap` adapter** (`ats=sitemap`, `extra` = sitemap URL): fetch the sitemap (follow one level of sitemap indexes), keep URLs whose path matches `/careers/`, `/jobs/`, `/job/`, or `/openings/`. Each URL is one job; fetch the page only for **new** URLs to read its `<title>` / first `<h1>` and body text. Hard cap: 200 new pages per run.
- **9c. `pagewatch` (top 50 only; `extra` = URL):** hash the visible text (scripts/styles removed, digits stripped to ignore counters) and store it in `meta` under `pagewatch:{company_key}`. If the hash changes, send one alert line "Careers page changed: {name} {url}" in the next email (this is a hint, not a parsed job). Never record it as a Job.
- **9d. Aggregator API (e.g. Adzuna):** only if its current documentation confirms India coverage and its terms allow this use. Requires the human to register for API keys (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`). Query terms come from `filters.roles_include`. If India isn't supported, skip and tell the human.
- **9e. Hacker News "Who is hiring" (only if asked):** discovery input only; never parse comments into `Job` records or alert directly.
  - Search the monthly story with `https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=Who%20is%20hiring`.
  - Select the newest story by `created_at_i` whose title is "Who is hiring" (exclude "Who wants to be hired"), then fetch `https://hn.algolia.com/api/v1/items/{story_id}`.
  - Inspect top-level `children` comments only. From each non-deleted comment, get the first non-empty text line, split on `|` (also accept em-dash separators), and use the first field as the company name. Ignore comments without a recognizable delimiter; deduplicate names.
  - `python -m src.main discover-hn` writes `config/inputs/hn_who_is_hiring_YYYY-MM.txt`. It is a generated file, refreshed on rerun for that thread; `scripts/discover_ats.py` reads `config/inputs/` and probes its companies against the supported ATS endpoints. Do not modify seed files.
  - Run the command manually once a month before `python -m src.main discover`; do not add it to the 15-minute crawl workflow.
  - Verify endpoint response shapes live before implementation. Tests use saved synthetic fixtures and never access the network.
- **9g. Y Combinator India companies:** discovery input only. `python -m src.main discover-yc` downloads `https://yc-oss.github.io/api/companies/all.json` (the open yc-oss dataset; verified fields: `name`, `website`, `regions`, `all_locations`, `team_size`, `stage`, `status`, `batch`), keeps `status` ∈ {Active, Public} with `"India"` in `regions`, writes `config/inputs/yc_india.csv` (`name,website`), and upserts `config/company_meta.csv` (segment from team size, `large` for Public; `hq_country` = India when the first listed location is in India, else `other`; `source=yc:<batch>`). Run monthly before `discover`. Tests use `tests/fixtures/yc_companies_sample.json`.
- **9h. Funding-news feeds (Indian seed / Series A / B startups):** discovery input only. `python -m src.main discover-funding` reads `https://entrackr.com/rss` and `https://inc42.com/buzz/feed/` (both verified live 2026-10-19; robots.txt allows them). It parses single-deal headlines ("X raises $N Mn in Series A", "Investor leads ... round in X", "investor backs X with ...") and the deal table inside Inc42's weekly Funding Galore article (`content:encoded`; columns Name, Sector, Funding Round Size, Funding Round Type). IPO/anchor, VC-fund, results, and weekly-summary headlines are skipped. Segment comes from the named round (pre-seed/seed/angel → seed, Series A, Series B, C+ → series_c_plus); with no round named it is estimated from size (≤$5 Mn seed, ≤$20 Mn A, ≤$50 Mn B, else C+; ₹1 Cr ≈ $0.115 Mn). Deals accumulate in `config/inputs/funding_news.csv` (`name,website,segment,stage,amount_usd_mn,sector,published,source,link`; newest round per company). `company_meta.csv` is upserted with the funding segment, keeping any known team size; manual rows are untouched. Because feeds keep only a few days, `.github/workflows/funding-news.yml` runs this daily and commits only those two files to `main`. It never edits `companies.csv`; run `discover` on the input file, review, then `--merge` locally. Tests use synthetic fixtures with the live feed structure.
- **9f. Common Crawl ATS slug harvesting (only if asked):** a separate weekly job, never part of the 15-minute crawler.
  - Read recent collection IDs from `https://index.commoncrawl.org/collinfo.json`; query the official CDX index for Greenhouse (`boards.greenhouse.io`, `job-boards.greenhouse.io`), Lever (`jobs.lever.co`), Ashby (`jobs.ashbyhq.com`), Workable (`apply.workable.com`), and SmartRecruiters (`jobs.smartrecruiters.com`) job URLs.
  - Use low-rate URL-prefix partitions, honor `Retry-After`, recursively split failed prefixes, and persist completed/pending work. The index can time out for broad queries; report unresolved partitions rather than silently treating them as empty. Do not overload the Common Crawl index.
  - Extract a slug only from a recognized job-detail URL. Screen each unseen `ats:slug` once through its public ATS adapter. Keep the board if any listed job has an India location or an intern-like title; cache both accepted and rejected outcomes. Temporary network failures are not cached as rejections.
  - Append passing boards to `config/companies.csv` on a review branch; use tier 2 when India jobs exist, otherwise tier 3. The weekly GitHub Actions workflow opens/updates a PR and never pushes directly to `main`.
  - Keep the screening cache in `config/commoncrawl_harvest.json` so rejected boards are not rechecked. Cap work per run and retain pending boards for the next run.
  - Tests use local response fixtures/mocks only. Verify Common Crawl response formats live in a bounded manual smoke test before enabling the weekly schedule.


---

# PART D: DEFINITION OF DONE

- [ ] `pytest -q` is green; no test touches the network.
- [ ] `run` works locally and on GitHub Actions every 15 minutes.
- [ ] First crawl of any new company never floods your inbox (silent seeding).
- [ ] One failing/blocked company never breaks a run or closes its jobs.
- [ ] You receive a `[New Job]` email within ~30 min of a matching job appearing at a Tier 1 company.
- [ ] Daily digest arrives with `jobs.xlsx` attached.
- [ ] No secrets in the repo or logs.
- [ ] README updated with real counts (companies crawled, jobs seen) for your portfolio.
