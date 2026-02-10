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
>
> Return a JSON object with:
> - `skills`: List of ALL hard skills, tools, frameworks, methodologies, and technical competencies mentioned. Aim for 15-20 items.
> - `experience_level`: One of "Junior" (<2 years), "Mid" (2-5 years), "Senior" (5-10 years), "Lead" (10+ years), "CTO".
> - `years_of_experience`: (int) Total years of professional experience. Calculate from work history dates.
> - `roles`: List of 5 job titles the candidate is suited for, ordered most to least specific. Include both English and local-language titles.
> - `languages`: List of spoken languages with proficiency level (e.g., "German B2", "English Native").
> - `domain_expertise`: List of all industries and domains the candidate has worked in.
> - `certifications`: List of professional certifications, accreditations, or licenses. Empty list if none.
> - `education`: List of degrees with field of study and university name if mentioned.
> - `summary`: A 2-3 sentence professional summary describing the candidate's core strengths and career trajectory.

**Generation Config:**
- Temperature: 0.3
- Max tokens: 8192 (high to accommodate gemini thinking tokens)

---

## 2. The Headhunter (Search Query Generator)

**Role:** Search Engine Optimization Specialist
**Input:** The "Profiler" JSON summary + User's desired location (e.g., "Munich, Germany").
**Output:** A JSON array of 20 search query strings optimized for Google Jobs.

**System Prompt:**
> You are a Search Specialist. Based on the candidate's profile and location, generate 20 distinct search queries to find relevant job openings in Europe.
>
> IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.
>
> CRITICAL: Always use LOCAL city names, not English ones. For example use "München" not "Munich", "Köln" not "Cologne", "Wien" not "Vienna", "Zürich" not "Zurich", "Praha" not "Prague".
>
> ORDER queries from MOST SPECIFIC to MOST GENERAL — this is critical:
> 1. Queries 1-5: Exact role titles + local city name
> 2. Queries 6-10: Broader role synonyms + city
> 3. Queries 11-15: Industry/domain keywords without city or with "remote"
> 4. Queries 16-20: Very broad industry terms
>
> Strategy for MAXIMUM coverage:
> - Include BOTH English and local-language job titles
> - Use different synonyms for the same role

**Generation Config:**
- Temperature: 0.5
- Max tokens: 8192

**Post-processing:**
- Queries missing a location keyword (words from the user's location string, or "remote") get the target location auto-appended before searching.
- English city names are automatically translated to local names (e.g., Munich → München, Vienna → Wien, Cologne → Köln) via a regex-based replacement in `search_agent.py:_localise_query()`.

**Search behaviour:**
- Google `gl=` country code is inferred from the location string via `_infer_gl()` (maps ~60 country/city names to 2-letter codes, defaults to `"de"`).
- Searches stop early once 50 unique jobs have been collected, saving SerpAPI quota.
- Listings from questionable job portals (BeBee, Jooble, Adzuna, etc.) are filtered out at parse time. Jobs with no remaining apply links after filtering are discarded entirely.

---

## 3. The Screener (Job Evaluator)

**Role:** Hiring Manager
**Input:**
1. The Candidate's structured profile (skills, experience, education, certifications, summary).
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
> You are a career advisor. Given a candidate profile and their evaluated job matches, write a brief summary.
>
> Structure your response with these sections:
> 1. **Market Overview** (2-3 sentences): How well does this candidate fit the current job market? How many strong matches vs weak ones?
> 2. **Top Opportunities** (bullet list): The 3-5 strongest matching roles/companies and why they stand out.
> 3. **Skill Gaps** (bullet list): The most frequently missing skills across job listings. Prioritise by how often they appear.
> 4. **Career Advice** (2-3 sentences): Actionable next steps — certifications to pursue, skills to learn, or positioning tips.

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

> bebee, trabajo, jooble, adzuna, jobrapido, neuvoo, mitula, trovit, jobomas, jobijoba, talent, jobatus, jobsora, studysmarter, jobilize, learn4good, grabjobs, jobtensor

Listings with no remaining apply links after filtering are skipped entirely.

---

## 6. Pydantic Schemas

```python
class CandidateProfile(BaseModel):
    skills: list[str]                    # 15-20 hard skills
    experience_level: Literal["Junior", "Mid", "Senior", "Lead", "CTO"]
    years_of_experience: int             # calculated from work history
    roles: list[str]                     # 5 titles, EN + local language
    languages: list[str]                 # with proficiency levels
    domain_expertise: list[str]
    certifications: list[str]            # empty list if none
    education: list[str]                 # degree + university
    summary: str                         # 2-3 sentence professional summary

class ApplyOption(BaseModel):
    source: str                          # e.g., "LinkedIn", "Company Website"
    url: str                             # direct application URL

class JobListing(BaseModel):
    title: str
    company_name: str
    location: str
    description: str
    link: str
    posted_at: str
    apply_options: list[ApplyOption]     # direct apply links (LinkedIn, career page, etc.)

class JobEvaluation(BaseModel):
    score: int                           # 0-100
    reasoning: str
    missing_skills: list[str]

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

**CLI flag:** `--no-cache` forces a fresh run ignoring all cached data.

---

## 8. Interfaces

### CLI (`main.py`)
- Entry point: `stellenscout <cv_path> [--location] [--min-score] [--jobs-per-query] [--num-queries] [--no-cache]`
- Rich terminal UI with spinners, colored tables, and detailed match view
- After evaluation, displays a career summary panel (Market Overview, Top Opportunities, Skill Gaps, Career Advice) above the results table

### Streamlit Web UI (`app.py`)
- Session-scoped cache directories under `.stellenscout_cache/<cv_file_hash>/`
- Auto-cleanup of session caches older than 24 hours (max 50 sessions)
- Sidebar: CV upload, location input, min score slider
- Main area: profile display, search queries expander, career summary expander, filterable/sortable job cards with direct apply buttons (LinkedIn, career page, etc.)
- API keys via `.streamlit/secrets.toml` or environment variables

---

## 9. CV Parser (`cv_parser.py`)

Supported formats:
- `.pdf` — via `pdfplumber`
- `.docx` — via `python-docx`
- `.md`, `.txt` — direct file read (UTF-8)
