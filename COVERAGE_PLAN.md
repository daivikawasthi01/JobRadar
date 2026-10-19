# JobRadar: Internship Coverage & No-Repeat Plan

Status: proposal, 2026-10-19. Nothing below is implemented yet. Each phase follows the
BUILD_SPEC rules: verify live, fixtures, offline tests, stop after each phase.

Goal: catch as many India tech internships (2027 batch) as the rules allow, with
seed / Series A / Series B startups first, then mid-size and large product companies,
and never send the same internship twice.

---

## 1. What is broken today (found in the code and data)

| # | Problem | Evidence | Effect |
|---|---|---|---|
| B1 | **The daily digest re-sends everything.** It attaches `jobs.xlsx` with every open match, every day. | `src/main.py` step 7, `src/export.py` Matches sheet | The same ~9 interns show up every morning until they close. |
| B2 | **State can be lost after the email has gone out.** The workflow has a 14-minute timeout. The crawl can use 11 minutes, then VACUUM, Excel, email and `xz -9` all run after that. If the job is killed or a step fails, "Save state" never runs (it has no `if: always()`). | `.github/workflows/crawl.yml` | The next run restores the old DB where `alerted=0`, so the same alert email goes out again. |
| B3 | **Only the first page of large boards is fetched.** SmartRecruiters returns 100 of `totalFound` (fixture: 100 of 949). Workable returns one page and a `nextPage` token (fixture: 5 of 19). Workday asks for `limit: 20` (fixture: 20 of 2000). | `src/adapters/smartrecruiters.py:42`, `workable.py:24`, `workday.py:68` | Most jobs at big companies are never seen. Jobs drift in and out of page 1, so they get closed and reopened over and over. |
| B4 | **Workday multi-location jobs are dropped.** The listing shows `locationsText` as `"2 Locations"`, so no country is detected. | `workday.py` parse | These get `country_unknown`, even when one of the locations is Bengaluru. |
| B5 | **Interns with no clear location are rejected.** `"Remote"`, `"Hybrid"`, `""` or `"Remote - APAC"` all give `country_unknown`. Indian startups post this way a lot. | `filters.py` country step | Lost matches at exactly the startups you care about most. |
| B6 | **The role allowlist is too narrow for intern titles.** For example "Intern", "Technology Intern", "Product Engineering Intern", "Software Intern", "Applied AI Intern", "Data Analyst Intern" and "Technical Intern" are all rejected as `role_not_included`. Separately, the `growth` exclusion kills "Growth Engineering Intern". | `config.yaml` `roles_include` | Lost matches. |
| B7 | **The company list is small and not aimed at India startups.** There are 506 boards: 208 Greenhouse, 162 Ashby, 82 SmartRecruiters, 54 Lever. Only 206 have any India job, and across all of them only about 2,959 of 32,191 jobs are in India. Discovery tried about 33k name/ATS/slug combinations. | `config/companies.csv`, `companies_candidates.csv`, `data/discover_progress.json` | Mostly US-heavy companies. Indian startups mostly use Keka, Darwinbox, Zoho Recruit, Freshteam, Lever, Ashby or a plain careers page, and none of those (except Lever/Ashby) are supported. |
| B8 | **The Actions budget is probably over the limit.** A private repo gets 2,000 free minutes a month. Running every 15 minutes is about 2,900 runs a month at 2+ billed minutes each, so roughly 6,000 to 9,000 minutes. | GitHub billing rules | Once the quota runs out, scheduled runs stop. That could explain why "it found 9 back then" and nothing since. **You need to check this in GitHub → Settings → Billing.** |
| B9 | **There is no way to say "I've seen this one".** Every digest shows the same rows. | n/a | Noise. You stop trusting the emails. |

### 1.1 Update after the repo went public (live state, 2026-10-19 02:32 UTC)

I audited the real `state` release DB (230 MB, 506 boards, about 34k jobs) and the last
100 Actions runs.

- **The "same 9 interns" are confirmed.** The 9 open matches were all first seen on Oct 15
  (Stripe, Rubrik, Tower Research, EnterPret, FamPay, HackerRank, CloudSEK ×2, Interview
  Kickstart). All of them have `alerted=1`, so the instant alert went out once. They keep
  coming back through the **daily digest (B1)**. Nothing new has matched since Oct 15.
- **B2 is unlikely.** All 100 recent runs are green and take about 2 minutes each,
  nowhere near the 14-minute timeout. The `if: always()` hardening still goes in.
- **B8 is resolved.** A public repo gets unlimited standard-runner minutes. Runs are
  being triggered every 15 minutes by `workflow_dispatch` (92 of the last 100), plus
  schedule.
- **The filters are not the main bottleneck.** There are 2,928 open India jobs across
  206 boards, but only 63 India intern/trainee/apprentice titles in total, and most of
  those are rightly rejected (HR, talent, marketing, finance). The real tech misses are
  roughly 6–8: Tower Research "Intern" (Gift City is not in the city list), Rubrik
  "Industrial Trainee" and "ENG Project/Program - Intern", CynLr "Fresher or Internship
  Roles", Instawork "QA Interns || Robotics" and "Hardware Intern — Robotics & AI", and
  Bureau "Product Analyst Intern". Phase 12 still fixes these. **The big lever is the
  company universe (B7):** the current 506 boards produce about 1 new India tech intern
  every few days.
- **B3 matters less than I first thought for this list:** every board is
  Greenhouse/Ashby/Lever/SmartRecruiters. Only the 82 SmartRecruiters boards lose jobs
  past page 1. Workable/Workday matter once they are added.

**Public-repo checks:** git history has no real secrets (only `xxxx` placeholders; your
real app password string appears 0 times). GitHub Secrets stay private. Note that the
`state` release (`jobs.db.xz`, `jobs.xlsx`) is now **publicly downloadable**. It holds
only public job postings and alert flags, no email addresses, but anyone can see what
you're searching for. If that bothers you, Phase 10 can encrypt the asset with a
repo secret.

**Revised priority:** Phase 10 (digest fix, small) → Phase 13–15 (company universe,
startups first, the biggest gain) → Phase 12 (filter recall) → Phase 11 (pagination).

---

## 2. Target design (end to end)

```
 discovery sources ──► candidates ──► review ──► companies.csv + company_meta.csv (segment, HQ country)
        │                                                     │
        │  (weekly/monthly, local or separate workflow)       ▼
        │                                   crawl (paginated adapters, tiered by segment)
        │                                                     │
        │                                                     ▼
        │                                filters (intern-first, HQ-aware location, review bucket)
        │                                                     │
        │                                                     ▼
        │                     store + alert ledger (fingerprint, never alert twice in 180 days)
        │                                                     │
        │                                                     ▼
        │          instant email/ntfy (segment-ranked) ─► daily digest = NEW in last 24h only
        ▼
 weekly coverage report (boards per segment, India interns found, broken boards)
```

### 2.1 No-repeat guarantees (fixes B1, B2, B9)

1. **Alert ledger table** `alert_log(fingerprint PRIMARY KEY, job_id, company, title, first_alerted_at)`.
   - `fingerprint = norm(company) | norm(title)`. `norm` lowercases, strips punctuation,
     removes years (`2026`, `2027`), seasons (`summer`, `winter`), duration words
     (`6 month`) and location suffixes. The point is that a reposted internship, the same
     intern listed for 3 cities, or the same job on two ATS boards all collapse to one alert.
   - Before alerting, skip any fingerprint already in the ledger from the last 180 days.
     The ledger is never pruned along with closed jobs.
2. **Crash-safe ordering in the workflow:**
   - "Save state" runs with `if: always()`, so a crawler crash still saves the alert marks.
   - The fetch budget drops from 11 to 7 minutes, `xz -9` becomes `xz -6` (much faster),
     and `timeout-minutes` goes to 20. `concurrency` already queues overlapping runs.
   - After email: mark alerted, then commit the DB. If the upload fails, the ledger in
     the next good state still has every send that happened before the last good save.
3. **Digest only shows what's new:** "N new internships in the last 24h" plus a single
   count line ("12 earlier matches still open, see attached jobs.xlsx"). The full Excel
   stays attached for reference, but nothing old is listed in the email body again.
4. **Optional "done" list:** `config/dismissed.txt`, one job URL or fingerprint per line
   (applied / not interested). Those are greyed out in the Excel and left out of digest
   counts. This is a one-file suppression list, not an application tracker (B14 still holds).

### 2.2 Coverage: crawling correctly (fixes B3, B4)

- SmartRecruiters: page with `offset` + `limit=100` until `totalFound`.
- Workable: follow `nextPage` until it is missing.
- Workday: page with `offset` (20 per page) until `total`, up to a hard cap per run
  (e.g. 2,000). Fetch job detail only for postings whose listing shows `"N Locations"` and
  whose title already passes the intern check (keeps requests low).
- **Guard:** if a paginated fetch fails partway through, treat the whole board fetch as
  an error (record_error). Never treat it as a short list that closes jobs.

### 2.3 Coverage: filters built for internships (fixes B5, B6)

- **Intern-first rule:** when a title has an intern-type word, match it unless the title
  hits a **non-tech blocklist** (sales, marketing, HR, talent, finance, legal, content,
  design*, business development, customer success, operations-only). This flips the
  current allowlist into a blocklist for interns, so "Intern", "Tech Intern",
  "Product Engineering Intern" and "Applied AI Intern" all match. The plan flags them
  `role_signal=generic` or `role_signal=tech` and puts tech first.
  (*Design is open: you decide whether UI/UX intern counts.)
- **Wider intern vocabulary:** `intern, internship, trainee, apprentice, co-op, student,
  summer analyst, fellowship, PPO, graduate trainee, campus`.
- **HQ-aware location:** `company_meta.csv` gets an `hq_country` column. When location is
  empty / Remote / Hybrid / "APAC" / "Asia" and `hq_country = India`, treat the job as
  India with `country_signal=hq_default`. More cities get added too (Gandhinagar / GIFT
  City, Visakhapatnam, Bhopal, Mangaluru, Manipal, Goa, Dehradun, Kanpur, Remote-India
  variants).
- **Review bucket instead of a silent drop:** borderline rejects go to a "Maybe" sheet and
  a short "Maybe" section in the digest. That covers `grad_year_mismatch` when the year is
  2026/2028, `country_unknown` for interns, and generic-role interns at non-Indian HQs.
- **Recall test set:** a `python -m src.main audit-rejects` command lists every rejected
  job whose title contains an intern word, with its reason. You review it once and each
  wrong reject becomes a test case (per START_HERE §4). The existing B8.5 tests stay as
  they are. Where the new behaviour contradicts a spec case (e.g. #27 "Research Intern"
  rejected), I'll raise it with you before touching the test.

### 2.4 Coverage: the company universe, startups first (fixes B7)

**New metadata file** `config/company_meta.csv`: `company_key,segment,hq_country,source`.
`segment` ∈ `seed | series_a | series_b | series_c_plus | midsize | large | unknown`.
It is kept separate so the `companies.csv` format (B3.1) does not change.

**Segment drives priority:**

| Segment | Poll interval | Email order | Push (ntfy) |
|---|---|---|---|
| seed / series_a / series_b | every run | top, tagged `[Seed]` / `[A]` / `[B]` | yes, instantly |
| series_c_plus / midsize | hourly | middle | no |
| large | hourly (they post on cycles) | bottom | no |
| unknown | tier rules as today | bottom | no |

**Discovery sources, in priority order.** All are public and allow this kind of use;
each one gets a ToS/robots check before it's enabled.

1. **Your two company databases** → `config/inputs/` (still the best signal; A6 in the spec).
2. **YC companies with India presence:** the open-source `yc-oss/api` JSON dump on GitHub
   (static files, no scraping). Filter `regions` contains India and `isHiring`. Stage gets
   tagged from batch + team size. This is the main seed/Series A source.
3. **Funding-news RSS** (Inc42 "Funding Galore", Entrackr, YourStory funding tags). Only
   headlines get parsed into company names + round (`Seed`, `Series A`, ...). Freshly
   funded companies are the ones hiring interns. Monthly, local, discovery input only.
4. **Common Crawl harvest (already built)**: extend it to the India ATS hosts below.
5. **HN Who's Hiring (already built)**: low India yield, keep it monthly.
6. **Website-first discovery:** for every company with a domain, check `/careers` and
   `/jobs` and read which ATS it links to. This already exists but only runs when slug
   probing fails, and only for rows with a website. Plan: always run it for
   seed/A/B companies, and add regexes for the India ATS list below.

**New adapters for India-heavy ATSs** (Phase 8-style: verify live, fixture, tests, then
enable; only if each one has a public, unauthenticated job endpoint):

| ATS | Typical users | Public board pattern to verify |
|---|---|---|
| Keka Hire | Indian seed to mid-size | `{x}.keka.com/careers` |
| Darwinbox | Indian mid-size / large | `{x}.darwinbox.in/ms/candidate/careers` |
| Zoho Recruit | Indian SMB / startups | `{x}.zohorecruit.in/jobs/Careers` |
| Freshteam | Indian startups | `{x}.freshteam.com/jobs` |
| Recruitee / BambooHR / Breezy | already built | n/a |
| SuccessFactors, Oracle Cloud, iCIMS, Phenom | large companies | later, only if a stable public JSON endpoint exists |

For startups with no ATS (Notion / Google Form / plain HTML careers pages), use the
existing JSON-LD adapter where it applies, and Phase 9c **pagewatch** for the top ~100
seed/A/B companies. It sends a "careers page changed" hint, not a parsed job.

**Target:** go from 506 boards (206 with India jobs) to about 3,000–5,000 boards, with at
least 1,500 India-hiring and at least 800 tagged seed/A/B. These are estimates. The
weekly coverage report (2.6) will show the real numbers.

### 2.5 Scheduling and cost (fixes B8)

**Resolved:** the repo is public now, so minutes are unlimited and every-15-minute runs
are fine. These options are kept for the record:
- **A. Stay on Actions, run hourly.** That fits about 2,000 minutes a month. Seed/A/B boards
  still get checked every run. An internship usually stays open for days, so hourly is fine.
- **B. Run every 15 min locally** with macOS `launchd`, and keep Actions as an hourly backup
  that only saves state. Free, but only while your Mac is awake.
- **C. Make the repo public.** That gives unlimited minutes, but the state release (job DB)
  becomes public too. Not recommended.

### 2.6 Monitoring

A weekly "coverage report" email (Monday) and a Stats sheet in the Excel with:
- boards per segment / ATS, how many are erroring or disabled, how many have zero jobs for 30+ days
- India intern jobs seen this week, by segment
- top reject reasons for intern titles (feeds the filter tuning in 2.3)
- new boards added by each discovery source

---

## 3. Phases (one at a time, stop after each)

| Phase | Scope | Fixes | Acceptance checks |
|---|---|---|---|
| **10. Stop repeats + reliability** | alert ledger + fingerprint, digest shows only new, `dismissed.txt`, workflow `if: always()` + time budget + `xz -6`, schedule decision (2.5) | B1 B2 B8 B9 | A test re-inserts the same intern with a new job_id / city / ATS and gets 0 alerts. A test kills the run after the email and the next run sends 0. The digest test lists only rows from the last 24h. |
| **11. Pagination** | SmartRecruiters, Workable, Workday paging + Workday multi-location detail | B3 B4 | Fixtures for page 2. A failed page 2 counts as an error and closes no jobs. Live smoke test shows count == `totalFound`. |
| **12. Intern-first filters** | blocklist mode for interns, wider vocabulary, HQ-aware location, Maybe bucket, `audit-rejects` | B5 B6 | All existing B8.5 tests pass (or I raise conflicts with you first). New cases for each title/location in B5/B6. `audit-rejects` runs over real data. |
| **13. Segments + priority** | `company_meta.csv`, segment-based polling, ordering, tags, ntfy for seed/A/B | B7 | A seed-company match comes first in the email with an `[Seed]` tag. |
| **14. Discovery sources** | YC OSS dump, funding RSS, website-first discovery for all domains, Common Crawl extended | B7 | Each source: live check, fixture, dry run producing candidates. You spot-check 20 before merge. |
| **15. India ATS adapters** | Keka, Darwinbox, Zoho Recruit, Freshteam (each only if a public endpoint is verified live) | B7 | Same as Phase 8 for each one. |
| **16. Coverage report** | weekly report + Stats sheet | n/a | Report email renders and the numbers match DB queries. |

Order reasoning: 10 first, because a noisy alert channel is worse than no channel.
11–12 are cheap and raise recall on boards you already crawl. 13–15 widen the funnel,
with startups first.

---

## 4. What this cannot cover (be realistic)

The rules forbid scraping these, and many seed-stage startups post **only** there:
LinkedIn, Naukri, Indeed, Glassdoor, and in practice Internshala, Wellfound (AngelList),
Instahyre and Cutshort (their terms prohibit automated scraping). JobRadar covers the
company-owned side. To cover the rest:
- Turn on job alerts inside LinkedIn / Internshala / Wellfound themselves and route them to
  the same Gmail label. Ten minutes of setup, and the ToS allows it.
- For seed/A/B companies in the list that have **no** careers page, the coverage report
  lists them. Cold-email the founder or CTO. At that stage this often works better than
  applying.

## 5. Open questions for you

1. ~~How do the 9 come back?~~ Answered: the daily digest.
2. ~~Actions health / minutes?~~ Answered: green, about 2 minutes per run, unlimited now.
3. ~~Live DB?~~ Audited (see 1.1).
4. Is it OK that the state release is public, or should Phase 10 encrypt it?
5. Is UI/UX design intern in scope? Data analyst intern? Product (APM) intern?
6. Are 2026-batch internships ever useful for you (some accept final-year 2027 too), or is
   a 2026-only posting a hard no?
