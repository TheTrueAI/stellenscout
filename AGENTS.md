# Agent Architectures

This document defines the persona, context, and instruction sets for the AI agents used in StellenScout.

**LLM Provider:** Google AI Studio (Gemini)
**Model:** gemini-3-flash-preview
**Package:** `google-genai` (not the deprecated `google.generativeai`)

---

## 1. The Profiler (CV Parser & Summarizer)

**Role:** Senior Technical Recruiter
**Input:** Raw text extracted from a CV (PDF, DOCX, Markdown, or plain text).
**Output:** A structured JSON summary of the candidate.

**System Prompt:**
> You are an expert technical recruiter with deep knowledge of European job markets.
> You will be given the raw text of a candidate's CV. Extract a comprehensive profile.
>
> Be THOROUGH — capture everything relevant. Do not summarize away important details.
> Pay special attention to DATES and DURATIONS for each role and degree.
>
> Return a JSON object with:
> - `skills`: List of ALL hard skills, tools, frameworks, methodologies, and technical competencies mentioned. Include specific tools (e.g., "SAP", "Power BI"), standards (e.g., "ISO 14064", "GHG Protocol"), and methods. Aim for 15-20 items.
> - `experience_level`: One of "Junior" (<2 years), "Mid" (2-5 years), "Senior" (5-10 years), "Lead" (10+ years), "CTO".
> - `years_of_experience`: (int) Total years of professional experience. Calculate from work history dates.
> - `roles`: List of 5 job titles the candidate is suited for, ordered from most to least specific. Include both English and local-language titles where relevant.
> - `languages`: List of spoken languages with proficiency level (e.g., "German B2", "English Native", "French C1").
> - `domain_expertise`: List of all industries and domains the candidate has worked in.
> - `certifications`: List of professional certifications, accreditations, or licenses (e.g., "PMP", "AWS Solutions Architect"). Empty list if none.
> - `education`: List of degrees with field of study (e.g., "MSc Environmental Engineering", "BSc Computer Science"). Include the university name if mentioned.
> - `summary`: A 2-3 sentence professional summary describing the candidate's core strengths and career trajectory.
> - `work_history`: Array of work-experience objects, ordered MOST RECENT FIRST. Each object has:
>   - `title`: (string) Job title held.
>   - `company`: (string) Employer name.
>   - `start_date`: (string) e.g. "2020-03" or "2020". Use the best precision available.
>   - `end_date`: (string or null) null means this is the CURRENT role.
>   - `duration_months`: (int or null) Estimated duration in months. Calculate from dates; if dates are vague, estimate.
>   - `skills_used`: (list of strings) Key skills, tools, and technologies used in THIS specific role.
>   - `description`: (string) One-sentence summary of responsibilities/achievements.
> - `education_history`: Array of education objects. Each object has:
>   - `degree`: (string) e.g. "MSc Computer Science".
>   - `institution`: (string) University or school name.
>   - `start_date`: (string or null) Start date if available.
>   - `end_date`: (string or null) Graduation date, or null if still studying.
>   - `status`: One of "completed", "in_progress", "dropped". If the CV says "expected 2026" or has no graduation date and appears current, use "in_progress".
>
> Be precise about dates:
> - If the CV says "2020 – present", set end_date to null.
> - If it says "2018 – 2020", estimate duration_months (e.g. 24).
> - For education, mark degrees without a graduation date or with "expected" as "in_progress".
>
> Return ONLY valid JSON, no markdown or explanation.

**Generation Config:**
- Temperature: 0.3
- Max tokens: 8192 (high to accommodate gemini thinking tokens)

**Retry / recovery:** `profile_candidate()` attempts up to 3 calls. If the first response is invalid or incomplete JSON, a recovery suffix is appended to the prompt asking the LLM to re-generate the full profile as one valid JSON object.

---

## 2. The Headhunter (Search Query Generator)

**Role:** Search Engine Optimization Specialist
**Input:** The "Profiler" JSON summary + User's desired location (e.g., "Munich, Germany").
**Output:** A JSON array of 20 search query strings optimized for Google Jobs.

**System Prompt:**
> You are a Search Specialist. Based on the candidate's profile and location, generate 20 distinct search queries to find relevant job openings.
>
> IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.
>
> CRITICAL: Always use LOCAL names, not English ones. For example use "München" not "Munich", "Köln" not "Cologne", "Wien" not "Vienna", "Zürich" not "Zurich", "Praha" not "Prague", "Deutschland" not "Germany".
>
> **Adapt your strategy to the SCOPE of the Target Location:**
>
> A) If the location is a CITY (e.g. "München", "Amsterdam"):
>    1. Queries 1-5: Exact role titles + local city name
>    2. Queries 6-10: Broader role synonyms + city
>    3. Queries 11-15: Industry/domain keywords without city or with "remote"
>    4. Queries 16-20: Very broad industry terms
>
> B) If the location is a COUNTRY (e.g. "Germany", "Netherlands"):
>    1. Queries 1-5: Exact role titles + local country name (e.g. "Data Engineer Deutschland")
>    2. Queries 6-10: Same roles + major cities in that country (e.g. "Backend Developer München", "Backend Developer Berlin")
>    3. Queries 11-15: Broader role synonyms + country or "remote"
>    4. Queries 16-20: Very broad industry terms
>
> C) If the location is "remote", "worldwide", or similar:
>    1. Queries 1-10: Exact role titles + "remote"
>    2. Queries 11-15: Broader role synonyms + "remote"
>    3. Queries 16-20: Very broad industry terms without any location
>
> Additional strategy:
> - Include BOTH English and local-language job titles for the target country
> - Use different synonyms for the same role (e.g., "Manager", "Lead", "Specialist", "Analyst")

**Generation Config:**
- Temperature: 0.5
- Max tokens: 8192

**Post-processing:**
- Queries missing a location keyword (words from the user's location string, or "remote") get the target location auto-appended before searching.
- English city names are automatically translated to local names (e.g., Munich → München, Vienna → Wien, Cologne → Köln) via a regex-based replacement in `search_agent.py:_localise_query()`.
- English country names are also translated to local names (e.g., Germany → Deutschland, Austria → Österreich, Switzerland → Schweiz) via `_COUNTRY_LOCALISE` and `_COUNTRY_LOCALISE_PATTERN`.
- Both city and country localisation are applied to the query itself *and* to the auto-appended location suffix.

**Search behaviour:**
- Google `gl=` country code is inferred from the location string via `_infer_gl()` (maps ~60 country/city names to 2-letter codes, defaults to `"de"` for non-remote locations).
- For purely remote/global searches (location contains only tokens like "remote", "worldwide", "global", "anywhere", "weltweit"), `_is_remote_only()` returns `True` and `_infer_gl()` returns `None` — the `gl` param is omitted from SerpApi so results aren't country-biased.
- SerpApi's `location` parameter is passed for non-remote searches (the raw user-supplied string, e.g. "Munich, Germany") for geographic filtering. Omitted for remote searches.
- Searches stop early once 50 unique jobs have been collected, saving SerpAPI quota.
- Listings from questionable job portals (BeBee, Jooble, Adzuna, etc.) are filtered out at parse time. Jobs with no remaining apply links after filtering are discarded entirely.

---

## 3. The Screener (Job Evaluator)

**Role:** Hiring Manager
**Input:**
1. The Candidate's structured profile (skills, experience, education, certifications, summary, work_history, education_history).
2. A specific Job Description (Title, Company, Location, Description text).

**Output:** A JSON object with score, reasoning, and missing skills.

**System Prompt:**
> You are a strict Hiring Manager. Evaluate if the candidate is a fit for this specific job.
>
> **Scoring Rubric (0-100):**
> - **100:** Perfect match. Exact years of experience, tech stack, and language skills.
> - **80-99:** Great match. Missing minor "nice-to-haves" but strong core skills.
> - **50-79:** Potential fit. Strong skills but junior/senior mismatch or missing a key framework.
> - **0-49:** Hard pass. Wrong stack, wrong language, or wrong role entirely.
>
> **Temporal weighting — this is critical:**
> - Weight RECENT experience (last 3 years) and LONGER tenures significantly more than old or brief roles.
> - A skill used for 3+ years in the most recent role is strong evidence. The same skill from a 3-month internship 10 years ago is weak evidence.
> - For education: a degree marked "in_progress" means the candidate has NOT graduated yet.
> - If no work history is provided, fall back to the flat skills list and experience level.
>
> **Critical constraints:**
> - If the job requires fluency in a local language (e.g., German, French, Dutch) and the candidate lacks that proficiency (A1/A2 or not listed), the score must be capped at 30.
> - Pay attention to visa/work permit requirements if mentioned.

**Generation Config:**
- Temperature: 0.2 (low for consistent scoring)
- Max tokens: 8192

**Execution:** Jobs are evaluated in parallel using `ThreadPoolExecutor(max_workers=10)` with thread-safe progress tracking. On API errors, a fallback score of 50 is assigned.

---

## 4. The Advisor (Career Summary Generator)

**Role:** Career Advisor
**Input:**
1. The Candidate's structured profile.
2. The full list of evaluated jobs (sorted by score descending).

**Output:** A markdown-formatted career summary string (not JSON).

**System Prompt:**
> You are a career advisor. Given a candidate profile and their evaluated job matches, write a very brief summary. Use a friendly and encouraging tone, but be honest about the fit. Focus on actionable insights. Use emojis to make it more engaging.
>
> Structure your response in plain text with these sections:
> 1. **Market Overview** (2-3 sentences): How well does this candidate fit the current job market? How many strong matches vs weak ones?
> 2. **Skill Gaps** (bullet list): The most frequently missing skills across job listings. Prioritise by how often they appear.
> 3. **Career Advice** (2-3 sentences): Actionable next steps — certifications to pursue, skills to learn, or positioning tips.
>
> Be concise and specific to THIS candidate. Use markdown formatting.

**Generation Config:**
- Temperature: 0.5
- Max tokens: 2048

**Pre-processing:** Before calling the LLM, `generate_summary()` computes:
- Score distribution bins (≥80, 70-79, 50-69, <50)
- Top 10 missing skills by frequency across all evaluated jobs
- Compact text representation of the top 10 matches (title, company, score, reasoning, missing skills)

---

## 5. Configuration

### API Parameters

```python
# Gemini model and retry
MODEL = "gemini-3-flash-preview"
MAX_RETRIES = 5
BASE_DELAY = 3  # seconds, exponential backoff with jitter

# SerpApi Google Jobs parameters
SERPAPI_PARAMS = {
    "engine": "google_jobs",
    "hl": "en",           # Language: English (for broader results)
}
# gl= country code is inferred from location (see _infer_gl())
# Pagination uses next_page_token (not deprecated 'start' parameter)
```

### Rate Limiting & Retry

- Exponential backoff with jitter for `429 RESOURCE_EXHAUSTED` and `503 UNAVAILABLE` errors
- Centralized in `llm.py:call_gemini()` — 5 retries with `3 * 2^attempt + random(0,1)` second delays
- SerpApi: 100 searches/month on free tier

### Blocked Job Portals

Jobs from the following portals are discarded during search result parsing (see `search_agent.py:_BLOCKED_PORTALS`):

> bebee, trabajo, jooble, adzuna, jobrapido, neuvoo, mitula, trovit, jobomas, jobijoba, talent, jobatus, jobsora, studysmarter, jobilize, learn4good, grabjobs, jobtensor, zycto, terra.do, jobzmall, simplyhired

Listings with no remaining apply links after filtering are skipped entirely.

---

## 6. Pydantic Schemas

All models use `Field()` with descriptions and defaults where appropriate.

```python
class WorkEntry(BaseModel):
    title: str                           # job title held
    company: str                         # employer name
    start_date: str                      # e.g. "2020-03" or "2020"
    end_date: str | None = None          # null = current role
    duration_months: int | None = None   # estimated from dates
    skills_used: list[str] = []          # skills exercised in this role
    description: str = ""                # one-sentence summary

class EducationEntry(BaseModel):
    degree: str                          # e.g. "MSc Computer Science"
    institution: str = ""                # university / school
    start_date: str | None = None
    end_date: str | None = None          # null = still studying
    status: Literal["completed", "in_progress", "dropped"] = "completed"

class CandidateProfile(BaseModel):
    skills: list[str]                    # 15-20 hard skills
    experience_level: Literal["Junior", "Mid", "Senior", "Lead", "CTO"]
    years_of_experience: int = 0         # calculated from work history
    roles: list[str]                     # 5 titles, EN + local language
    languages: list[str]                 # with proficiency levels
    domain_expertise: list[str]
    certifications: list[str] = []       # empty list if none
    education: list[str] = []            # degree + university
    summary: str = ""                    # 2-3 sentence professional summary
    work_history: list[WorkEntry] = []   # chronological, most recent first
    education_history: list[EducationEntry] = []  # with completion status

class ApplyOption(BaseModel):
    source: str                          # e.g., "LinkedIn", "Company Website"
    url: str                             # direct application URL

class JobListing(BaseModel):
    title: str
    company_name: str
    location: str
    description: str = ""
    link: str = ""
    posted_at: str = ""
    apply_options: list[ApplyOption] = []  # direct apply links (LinkedIn, career page, etc.)

class JobEvaluation(BaseModel):
    score: int                           # 0-100, constrained ge=0 le=100
    reasoning: str
    missing_skills: list[str] = []

class EvaluatedJob(BaseModel):
    job: JobListing
    evaluation: JobEvaluation
```

---

## 7. Caching (`cache.py`)

All pipeline results are cached to JSON in `.stellenscout_cache/` to minimize API usage across runs.

```
.stellenscout_cache/
├── profile.json       # keyed by CV hash (SHA-256)
├── queries.json       # keyed by profile hash + location
├── jobs.json          # date-stamped, merged with existing jobs
└── evaluations.json   # keyed by profile hash, append-only per job
```

**Cache invalidation:**
- **Profile**: CV text hash changes → recompute
- **Queries**: Profile hash or location changes → recompute
- **Jobs**: Searched today → reuse; new day → search API and merge
- **Evaluations**: Profile hash changes → clear all; otherwise only unevaluated jobs are sent to Gemini

---

## 8. Streamlit Web UI (`app.py`)

Three-phase UI flow:
- **Phase A (Landing):** Hero section, CV consent checkbox, file uploader, recent DB jobs
- **Phase B (CV uploaded):** Location input form, AI profile display, "Find Jobs" button
- **Phase C (Results):** Filterable/sortable job cards, career summary, newsletter subscription

Features:
- Session-scoped cache directories under `.stellenscout_cache/<cv_file_hash>/`
- Auto-cleanup of session caches older than 24 hours (max 50 sessions)
- Sidebar: status panel, min score slider, secondary CV uploader, legal links
- GDPR consent checkbox required before CV upload (consent text versioned as `_CONSENT_TEXT_VERSION`)
- CV file size limit: 5 MB; text truncated at 50,000 chars
- Rate limiting: 30-second cooldown between pipeline runs (session-based + IP-based)
- IP-based rate limiting: module-level `_ip_rate_limit` dict tracks `{ip: timestamp}`; extracts client IP from `X-Forwarded-For` header; stale entries purged after 5 minutes
- Email format validation: regex check (`^[^@\s]+@[^@\s]+\.[^@\s]+$`) before `add_subscriber()` rejects obviously invalid addresses
- Error message sanitization: all `st.error()` calls show generic messages; real exceptions logged server-side via `logger.exception()`
- Newsletter subscription with Double Opt-In (see §10)
- API keys via `.streamlit/secrets.toml` or environment variables

### Streamlit Pages
- `pages/verify.py` — Email verification endpoint (`/verify?token=...`)
- `pages/unsubscribe.py` — One-click unsubscribe endpoint (`/unsubscribe?token=...`)
- `pages/impressum.py` — Legal notice (§ 5 DDG)
- `pages/privacy.py` — Privacy policy

---

## 9. CV Parser (`cv_parser.py`)

Supported formats:
- `.pdf` — via `pdfplumber` (max 50 pages; raises `ValueError` if exceeded)
- `.docx` — via `python-docx` (max 2,000 paragraphs; raises `ValueError` if exceeded)
- `.md`, `.txt` — direct file read (UTF-8)

---

## 10. Email & Subscriptions

### Double Opt-In Flow
1. User enters email + checks consent in the subscribe form
2. `db.add_subscriber()` creates a pending row with `is_active=False` and a `confirmation_token` (24-hour expiry)
3. `db.save_subscription_context()` stores the candidate's `profile_json`, `search_queries`, `target_location`, and `min_score` on the subscriber row
4. Jobs already displayed in the UI session are pre-seeded into `job_sent_logs` via `db.upsert_jobs()` + `db.log_sent_jobs()` so the first digest doesn't repeat them
5. `emailer.send_verification_email()` sends a confirmation link via Resend
6. User clicks the link → `pages/verify.py` calls `db.confirm_subscriber()` → sets `is_active=True`, then `db.set_subscriber_expiry()` sets `expires_at = now() + 30 days`
7. If email already active, the form shows "already subscribed" (no re-send)

### Auto-Expiry
- The 30-day clock starts at **DOI confirmation**, not signup (prevents wasted days while email is unconfirmed)
- `daily_task.py` calls `db.expire_subscriptions()` at the start of each run to deactivate expired subscribers
- On expiry, `db.delete_subscriber_data()` immediately wipes `profile_json`, `search_queries`, `target_location` (GDPR)
- Expired subscriber rows are purged after 7 days via `db.purge_inactive_subscribers()`

### Unsubscribe Flow
- Each daily digest email includes a `List-Unsubscribe` header and footer link
- `daily_task.py` generates a one-time `unsubscribe_token` (30-day expiry) per subscriber per run via `db.issue_unsubscribe_token()`
- `pages/unsubscribe.py` validates the token and calls `db.deactivate_subscriber_by_token()` which also calls `db.delete_subscriber_data()` to immediately wipe PII

### Re-subscription
- After expiry or unsubscribe, a user must start fresh: new CV upload, new session, new subscribe flow
- Old profile data is already deleted; there is no grace period

### Daily Digest (`daily_task.py`)
Per-subscriber pipeline, designed to run in GitHub Actions (or any cron scheduler):
1. Expire subscriptions past their 30-day window via `db.expire_subscriptions()`
2. Purge inactive subscriber rows older than 7 days via `db.purge_inactive_subscribers()`
3. Load all active subscribers with stored profiles via `db.get_active_subscribers_with_profiles()`
4. Aggregate & deduplicate search queries across all subscribers by location
5. Search once per unique (query, location) pair — saves SerpApi quota
6. Upsert all found jobs into DB with descriptions
7. For each subscriber:
   a. Reconstruct `CandidateProfile` from stored `profile_json`
   b. Filter out jobs already in their `job_sent_logs`
   c. Evaluate unseen jobs against their profile (Gemini)
   d. Filter by their `min_score` threshold
   e. Send daily digest email (with unsubscribe token)
   f. Log ALL evaluated jobs (not just good matches) to avoid re-evaluation
8. Exit

**Privacy:** All log messages reference subscribers by UUID (`sub=<id>`), never by email address. Email addresses are only used in the `send_daily_digest()` call.

Required env vars: `GOOGLE_API_KEY`, `SERPAPI_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `RESEND_API_KEY`, `RESEND_FROM`, `APP_URL`.

### Email Templates (`emailer.py`)
- `send_daily_digest()` — HTML table of job matches with score badges and apply links
- `send_verification_email()` — CTA button linking to the verify page
- Both include an impressum footer line built from `IMPRESSUM_NAME`, `IMPRESSUM_ADDRESS`, `IMPRESSUM_EMAIL` env vars

---

## 11. Database (`db.py` + `setup_db.py`)

**Provider:** Supabase (Postgres)

### Two client types
- `get_client()` — uses `SUPABASE_KEY` (anon/publishable), subject to RLS
- `get_admin_client()` — uses `SUPABASE_SERVICE_KEY` (service-role), bypasses RLS; required for all writes

### Row-Level Security (RLS) Policies
RLS is enabled on all tables. Explicit policies enforce defense-in-depth:
- **`subscribers`** — deny all anon access (all ops go through service role)
- **`job_sent_logs`** — deny all anon access
- **`jobs`** — allow anon SELECT (public data); deny anon INSERT, UPDATE, DELETE

### Tables

```sql
subscribers (
    id UUID PK,
    email TEXT UNIQUE,
    is_active BOOLEAN DEFAULT FALSE,
    confirmation_token TEXT,
    token_expires_at TIMESTAMPTZ,
    consent_text_version TEXT,
    signup_ip TEXT,
    signup_user_agent TEXT,
    confirmed_at TIMESTAMPTZ,
    confirm_ip TEXT,
    confirm_user_agent TEXT,
    unsubscribe_token TEXT,
    unsubscribe_token_expires_at TIMESTAMPTZ,
    unsubscribed_at TIMESTAMPTZ,
    profile_json JSONB,              -- serialized CandidateProfile
    search_queries JSONB,            -- list of query strings
    target_location TEXT,            -- e.g. "Munich, Germany"
    min_score INT DEFAULT 70,        -- score threshold
    expires_at TIMESTAMPTZ,          -- auto-expiry (confirmed_at + 30 days)
    created_at TIMESTAMPTZ DEFAULT now()
)

jobs (
    id UUID PK,
    title TEXT,
    company TEXT,
    url TEXT UNIQUE,
    location TEXT,
    description TEXT,                -- full job description for cross-subscriber evaluation
    created_at TIMESTAMPTZ DEFAULT now()
)

job_sent_logs (
    id UUID PK,
    subscriber_id UUID FK → subscribers(id) ON DELETE CASCADE,
    job_id UUID FK → jobs(id) ON DELETE CASCADE,
    sent_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (subscriber_id, job_id)
)
```

### Key operations
- `add_subscriber()` — upsert pending subscriber; returns existing row if already active
- `save_subscription_context()` — store profile, queries, location, min_score on subscriber row
- `set_subscriber_expiry()` — set `expires_at` (called on DOI confirmation)
- `confirm_subscriber()` — activate by token (checks expiry)
- `deactivate_subscriber()` / `deactivate_subscriber_by_token()` — unsubscribe + delete PII
- `expire_subscriptions()` — auto-deactivate + delete data for expired subscribers
- `delete_subscriber_data()` — wipe profile_json, search_queries, target_location
- `purge_inactive_subscribers()` — delete inactive rows older than 7 days (chunked deletes)
- `get_active_subscribers_with_profiles()` — active, non-expired subscribers with stored profiles
- `upsert_jobs()` — insert jobs (with descriptions), skip duplicates by URL
- `get_job_ids_by_urls()` — map URLs to DB UUIDs
- `get_sent_job_ids()` / `log_sent_jobs()` — track which jobs were emailed/shown to which subscriber
- `get_subscriber_by_email()` — look up subscriber by email

Schema setup: run `python setup_db.py` to check tables and print migration SQL.

---

## 12. Testing (`tests/`)

**Framework:** pytest + pytest-cov
**Linting:** ruff (lint + format), mypy (strict mode)
**Pre-commit:** all checks run via pre-commit hooks (see `.pre-commit-config.yaml`)

### Test files

| File | Module under test | What's covered |
|---|---|---|
| `test_llm.py` (12 tests) | `llm.py` | `parse_json()` (8 cases: raw, fenced, embedded, nested, errors) + `call_gemini()` retry logic (4 cases: success, ServerError retry, 429 retry, non-429 immediate raise) |
| `test_evaluator_agent.py` (8 tests) | `evaluator_agent.py` | `evaluate_job()` (4 cases: happy path, API error fallback, parse error fallback, non-dict fallback) + `evaluate_all_jobs()` (3 cases: sorted output, progress callback, empty list) + `generate_summary()` (2 cases: score distribution in prompt, missing skills in prompt) |
| `test_search_agent.py` (32 tests) | `search_agent.py` | `_is_remote_only()` (remote tokens, non-remote) + `_infer_gl()` (known locations, unknown default, remote returns None, case insensitive) + `_localise_query()` (city names, country names, case insensitive, multiple cities) + `_parse_job_results()` (valid, blocked portals, mixed, empty, no-apply-links) + `search_all_queries()` (location auto-append with localisation, no double-append, early stopping) + `TestLlmJsonRecovery` (profile_candidate and generate_search_queries retry/recovery) |
| `test_cache.py` (17 tests) | `cache.py` | All cache operations: profile, queries, jobs (merge/dedup), evaluations, unevaluated job filtering |
| `test_cv_parser.py` (6 tests) | `cv_parser.py` | `_clean_text()` + `extract_text()` for .txt/.md, error cases |
| `test_models.py` (23 tests) | `models.py` | All Pydantic models: validation, defaults, round-trip serialization |
| `test_db.py` (35 tests) | `db.py` | Full GDPR lifecycle: add/confirm/expire/purge subscribers, deactivate by token, data deletion, subscription context, job upsert/dedup, sent-log tracking. All DB functions mocked at Supabase client level |
| `test_emailer.py` (7 tests) | `emailer.py` | HTML generation: job row badges, job count, unsubscribe link, impressum line |
| `test_app_consent.py` (5 tests) | `app.py` | GDPR consent checkbox: session state persistence, widget key separation, on_change sync |

### Testing conventions
- All external services (Gemini API, SerpAPI, Supabase) are mocked — no API keys needed to run tests
- Shared fixtures in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- Test fixtures (text files) live in `tests/fixtures/`
- Run: `pytest tests/ -v`
- Coverage: `pytest tests/ --cov=stellenscout --cov-report=term-missing`

---

## 13. Licensing & Distribution Strategy

**License:** AGPL-3.0 (GNU Affero General Public License v3.0)

**Model:** Open Source + Hosted Paid Service (open-core)

The source code is publicly available on GitHub under AGPL-3.0. The AGPL requires that anyone who hosts a modified version of StellenScout must also release their source code — this protects against competitors forking the project and running a closed-source competing service.

### What users pay for

StellenScout is **free to self-host** (bring your own API keys). The official hosted version at the project domain charges a subscription fee for:
- Managed hosting (no API key setup required)
- SerpAPI & Gemini API quota included
- Daily digest email infrastructure
- Data retention & GDPR compliance handled

### Monetisation phases

1. **Phase 1 (Free launch):** Host a public demo with rate limits (e.g., 50 users cap or N searches/day). Build user base, validate demand, collect feedback.
2. **Phase 2 (Paid newsletter):** Introduce Stripe subscription (~€5-9/month) for the daily digest newsletter. Free tier remains for one-time job searches without newsletter.
3. **Phase 3 (Scale):** Expand based on traction — higher tiers, team plans, or API access.

### Why AGPL-3.0

- **Portfolio visibility:** Public GitHub repo with real production code is a strong hiring signal.
- **Community contributions:** Bug reports, PRs, and feedback from users who self-host.
- **Copyleft protection:** Competitors must open-source their modifications if they host a fork.
- **Trust:** Users can audit exactly what happens to their CV data.

---

## 14. Development Workflow & Agent Instructions

This section documents the development process and conventions for both human and AI agents working on this codebase. `CLAUDE.md` is a symlink to this file, so any AI coding agent (Copilot Chat, Claude Code CLI, etc.) will read these instructions automatically.

### Quick Reference (for AI agents)

```bash
# Activate the virtual environment first — ALWAYS required:
source .venv/bin/activate

# Test:    pytest tests/ -x -q
# Lint:    ruff check . && ruff format --check .
# Types:   mypy .
# Run app: streamlit run stellenscout/app.py
# All:     ruff check . && mypy . && pytest tests/ -x -q
```

### Conventions for AI agents

- **Always activate the virtual environment** (`source .venv/bin/activate`) before running any command (`pytest`, `ruff`, `mypy`, `streamlit`, etc.). The project's dependencies are installed only in `.venv`.
- Use `google-genai` package, NOT the deprecated `google.generativeai`
- Gemini model: `gemini-3-flash-preview`
- Pydantic models live in `stellenscout/models.py` — follow existing patterns
- All external services (Gemini, SerpAPI, Supabase, Resend) must be mocked in tests — no API keys needed to run `pytest`
- Shared test fixtures in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- Test fixture files (sample CVs, etc.) live in `tests/fixtures/`
- All DB writes use the admin client (`get_admin_client()`), never the anon client
- Log subscriber UUIDs, never email addresses
- All `st.error()` calls must show generic messages; real exceptions go to `logger.exception()`
- Follow the test file naming convention: `tests/test_<module>.py` for `stellenscout/<module>.py`
- After implementing changes, always run `pytest tests/ -x -q` to verify nothing is broken

### Development workflow

The recommended workflow for implementing tasks/issues:

1. **Pick the next unchecked task** from `ROADMAP.md`
2. **Plan the implementation** in Copilot Chat — describe the task, ask for a plan, review it
3. **Implement via Copilot Chat** (agent mode) — let the agent write code, create files, and run tests. It will implement → test → fix in a loop.
4. **Review the diff locally** — check changed files, run the Streamlit app once if needed
5. **Pre-push hooks handle quality gates** — `ruff`, `mypy`, `detect-secrets` run on commit; `pytest` runs on push (see `.pre-commit-config.yaml`)
6. **Push and create PR from the terminal:**
   ```bash
   git checkout -b feat/<task-slug>
   git add -A && git commit -m "feat: <description>"
   git push -u origin feat/<task-slug>
   gh pr create --fill
   ```
7. **GitHub Copilot reviews the PR** as a safety net (async, in CI)
8. **Merge:**
   ```bash
   gh pr merge --squash --delete-branch
   ```
9. **Mark the task as done** in `ROADMAP.md` (change `- [ ]` to `- [x]`)

### Tool allocation (token efficiency)

| Task | Tool | Rationale |
|---|---|---|
| Planning & architecture | Copilot Chat | Interactive discussion and design decisions |
| Multi-file implementation | Copilot Chat (agent mode) | Agentic loop: implements → tests → fixes autonomously |
| Small in-file edits | Copilot inline completions | Free, fast tab-complete |
| Pre-push code review | Copilot Chat | Review `git diff` output for bugs and convention deviations |
| PR review (second opinion) | GitHub Copilot on PR | Async safety net, catches things the local review missed |

### Pre-commit & pre-push hooks

Already configured in `.pre-commit-config.yaml`:
- **On commit:** trailing whitespace, YAML/TOML/JSON checks, large file check, merge conflict detection, private key detection, secrets scanning, ruff lint+format, mypy
- **On push:** full test suite (`pytest tests/ -x -q --tb=short`)

---

# Open Issues
- How to deal with many API requests for SerpAPI? It's quite expensive at scale.
- Make UI more engaging and personalized (use first name?).
- Some jobs don't exist anymore, but are still found by SerpAPI through job aggregators. Can we detect and filter these better?
- Let the user also personalize the search/evaluation by editing the generated queries, their profile, or having an extra "preferences" input (e.g., "I want to work in fintech", "I want a remote job", "I don't want to work for big corporations")?
- Let the user upload multiple CVs (e.g., one for software engineering, one for data science) and route them to different job searches?
- Let the user update their daily digest preferences (e.g., "only send me jobs with score > 80", "send me a weekly digest instead of daily")?
- Integrate Stripe for paid newsletter subscriptions (Phase 2).
- Write issue templates for the public repo.
- The SerpAPI query and the job evaluation are currently separate steps. Can we combine them to save API calls? For example, can we ask Gemini to generate the search queries AND evaluate the jobs in one go? Or can we at least evaluate each job as we parse it, instead of collecting them all and then evaluating? This might increase speed.
