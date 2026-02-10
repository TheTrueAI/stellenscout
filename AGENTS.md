# Agent Architectures

This document defines the persona, context, and instruction sets for the AI agents used in StellenScout.

**LLM Provider:** Google AI Studio (Gemini)
**Model:** gemini-2.5-flash
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
- Max tokens: 8192 (high to accommodate gemini-2.5-flash thinking tokens)

---

## 2. The Headhunter (Search Query Generator)

**Role:** Search Engine Optimization Specialist
**Input:** The "Profiler" JSON summary + User's desired location (e.g., "Munich, Germany").
**Output:** A JSON array of 10 search query strings optimized for Google Jobs.

**System Prompt:**
> You are a Search Specialist. Based on the candidate's profile and location, generate 10 distinct search queries to find relevant job openings in Europe.
>
> IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.
>
> Strategy for MAXIMUM coverage:
> - Generate a MIX of broad and specific queries
> - Include BOTH English and local-language job titles
> - Include some queries WITHOUT a city to find remote/nationwide jobs
> - Use different synonyms for the same role
> - Include 1-2 broad industry/domain queries

**Generation Config:**
- Temperature: 0.5
- Max tokens: 8192

**Post-processing:** Queries missing a location keyword (words from the user's location string, or "remote") get the target location auto-appended before searching.

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

## 4. Configuration

### API Parameters

```python
# Gemini model and retry
MODEL = "gemini-2.5-flash"
MAX_RETRIES = 5
BASE_DELAY = 3  # seconds, exponential backoff with jitter

# SerpApi Google Jobs parameters
SERPAPI_PARAMS = {
    "engine": "google_jobs",
    "hl": "en",           # Language: English (for broader results)
}
# Pagination uses next_page_token (not deprecated 'start' parameter)
```

### Rate Limiting & Retry

- Exponential backoff with jitter for `429 RESOURCE_EXHAUSTED` and `503 UNAVAILABLE` errors
- Centralized in `llm.py:call_gemini()` — 5 retries with `3 * 2^attempt + random(0,1)` second delays
- SerpApi: 100 searches/month on free tier

---

## 5. Pydantic Schemas

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

class JobListing(BaseModel):
    title: str
    company_name: str
    location: str
    description: str
    link: str
    posted_at: str

class JobEvaluation(BaseModel):
    score: int                           # 0-100
    reasoning: str
    missing_skills: list[str]

class EvaluatedJob(BaseModel):
    job: JobListing
    evaluation: JobEvaluation
```

---

## 6. Caching (`cache.py`)

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

## 7. Interfaces

### CLI (`main.py`)
- Entry point: `stellenscout <cv_path> [--location] [--min-score] [--jobs-per-query] [--no-cache]`
- Rich terminal UI with spinners, colored tables, and detailed match view

### Streamlit Web UI (`app.py`)
- Session-scoped cache directories under `.stellenscout_cache/<session_id>/`
- Auto-cleanup of session caches older than 24 hours
- Sidebar: CV upload, location, min score, jobs per query
- Main area: profile display, search queries, filterable/sortable results table, job detail expanders
- API keys via `.streamlit/secrets.toml` or environment variables

---

## 8. CV Parser (`cv_parser.py`)

Supported formats:
- `.pdf` — via `pdfplumber`
- `.docx` — via `python-docx`
- `.md`, `.txt` — direct file read (UTF-8)
