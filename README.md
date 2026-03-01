# Immermatch

[![CI](https://github.com/TheTrueAI/immermatch/actions/workflows/ci.yml/badge.svg)](https://github.com/TheTrueAI/immermatch/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)

AI-powered job matching for the European market. Upload your CV, and the app uses Google Gemini to analyze your profile, searches for relevant jobs via Google Jobs, and scores each listing against your skills and experience.

---
![Screenshot of the Immermatch web interface showing AI-powered job matching results](https://github.com/user-attachments/assets/e450bfb6-6aa0-4c24-aa53-be8695146b03)

---
## Features

- **CV Parsing** — Supports PDF, DOCX, Markdown, and plain text
- **AI Profile Extraction** — Gemini analyzes your CV to extract skills, experience, languages, and more
- **Smart Search** — Generates optimized search queries in English and local languages
- **Job Scoring** — Each job is scored 0–100 against your profile with detailed reasoning
- **European Market Focus** — Accounts for local language requirements, location keywords, and market norms
- **Daily Digest** — Subscribe for daily email digests with new AI-matched jobs
- **Privacy First** — GDPR-compliant with auto-expiry, double opt-in, and full data deletion
- **Caching** — Intelligent caching minimizes API calls across sessions

## Quick Start

### Prerequisites

- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com/app/apikey) API key (for Gemini)
- A [SerpApi](https://serpapi.com/) API key (for Google Jobs search)

### Setup

```bash
git clone https://github.com/TheTrueAI/immermatch.git
cd immermatch
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
# Edit .env with your keys
```

### Run the App

```bash
streamlit run immermatch/app.py
```

## How It Works

The app uses four AI agent personas powered by Gemini:

1. **The Profiler** — Extracts a structured candidate profile from raw CV text
2. **The Headhunter** — Generates optimized job search queries based on the profile
3. **The Screener** — Evaluates each job listing against the candidate profile (0–100 score)
4. **The Advisor** — Generates a career summary with market insights and skill gap analysis

Jobs are fetched from Google Jobs via SerpApi, deduplicated, and scored in parallel.

## Bundesagentur Provider Tuning

The Bundesagentur provider in `immermatch/bundesagentur.py` supports a configurable detail-fetch strategy:

- `api_then_html` (default): first tries `/pc/v4/jobdetails/{refnr}`, then falls back to scraping the public job-detail page if needed
- `api_only`: uses only the API detail endpoint
- `html_only`: uses only the public detail page parsing path

This helps keep job descriptions available even when one upstream detail path is unstable.

## Environment Variables

Copy `.env.example` to `.env` and fill in your keys. The app also supports `.streamlit/secrets.toml` for Streamlit Cloud deployments.

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Google AI Studio API key ([get one](https://aistudio.google.com/app/apikey)) |
| `SUPABASE_URL` | For newsletter | Supabase project URL ([dashboard](https://supabase.com/dashboard)) |
| `SUPABASE_KEY` | For newsletter | Supabase anon/publishable key |
| `SUPABASE_SERVICE_KEY` | For newsletter | Supabase service-role key (bypasses RLS) |
| `RESEND_API_KEY` | For newsletter | Resend API key ([get one](https://resend.com/)) |
| `RESEND_FROM` | For newsletter | Sender address, e.g. `Immermatch <digest@yourdomain.com>` |
| `APP_URL` | For newsletter | Public app URL for email verification links |
| `IMPRESSUM_NAME` | For newsletter | Legal notice: your full name (§ 5 DDG) |
| `IMPRESSUM_ADDRESS` | For newsletter | Legal notice: your postal address |
| `IMPRESSUM_EMAIL` | For newsletter | Legal notice: your contact email |

> **Note:** The one-time job search only requires `GOOGLE_API_KEY` (job listings come from the free Bundesagentur für Arbeit API). The Supabase, Resend, and Impressum variables are only needed for the daily digest newsletter feature.

## Database Setup

The daily digest feature requires a [Supabase](https://supabase.com/) Postgres database. To set up the schema:

1. Create a Supabase project and add `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_SERVICE_KEY` to your `.env`.
2. Run the schema checker:
   ```bash
   python setup_db.py
   ```
3. Copy the printed SQL into the [Supabase SQL Editor](https://supabase.com/dashboard/project/_/sql) and execute it.

The script creates three tables (`subscribers`, `jobs`, `job_sent_logs`) with appropriate indexes. RLS policies are applied to restrict anonymous access — see `AGENTS.md` §11 for details.

## Daily Digest

A GitHub Actions workflow runs `daily_task.py` every day at 07:00 UTC, sending personalized job digest emails to active subscribers.

**How it works per subscriber:**
1. Loads the stored candidate profile and search queries
2. Searches Google Jobs for new listings (shared across subscribers by location)
3. Evaluates unseen jobs against the profile via Gemini
4. Sends a digest email with matches above the subscriber's score threshold

**Setup for self-hosting:**
1. Complete the [Database Setup](#database-setup) above.
2. Add all environment variables from the table above as GitHub Actions secrets.
3. The workflow at `.github/workflows/daily-digest.yml` handles the rest.

See `AGENTS.md` §10 for the full email lifecycle (double opt-in, auto-expiry, unsubscribe).

## Testing

```bash
pip install -e ".[test]"
pytest tests/ -v --cov=immermatch --cov-report=term-missing
```

All external services (Gemini, SerpApi, Supabase, Resend) are mocked — no API keys needed to run the test suite.

Linting and type checking:

```bash
ruff check --fix . && ruff format --check .
mypy immermatch/ daily_task.py
```

Pre-commit hooks are available for automatic quality gates:

```bash
pip install -e ".[dev]"
pre-commit install --hook-type pre-commit --hook-type pre-push
```

## Project Structure

```
immermatch/
  app.py              # Streamlit web UI
  llm.py              # Gemini client and retry logic
  cv_parser.py        # CV text extraction (PDF/DOCX/MD/TXT)
  search_agent.py     # Profile extraction and job search
  evaluator_agent.py  # Job scoring and career summary
  models.py           # Pydantic data models
  cache.py            # JSON-based result caching
  db.py               # Supabase database layer
  emailer.py          # Email templates and sending (Resend)
  pages/
    verify.py         # Email verification endpoint
    unsubscribe.py    # One-click unsubscribe endpoint
    impressum.py      # Legal notice (§ 5 DDG)
    privacy.py        # Privacy policy
daily_task.py         # Daily digest cron job (GitHub Actions)
setup_db.py           # Database schema checker / migration helper
tests/                # tests (all mocked)
```

## Privacy & Data Handling

Immermatch is designed with GDPR compliance in mind:

- **Session-scoped caching** — CV data is cached locally per session and auto-cleaned after 24 hours
- **Double opt-in** — Newsletter subscriptions require email verification
- **30-day auto-expiry** — Subscriber data is automatically deleted after 30 days
- **Immediate data deletion** — Unsubscribing immediately wipes stored profile data
- **No tracking cookies** — Only Streamlit's technically necessary session cookies are used
- **Open source** — Users can audit exactly what happens to their data

See the privacy policy at `/privacy` in the running app for full details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding conventions, and how to submit pull requests.

## License

[AGPL-3.0](LICENSE) — You're free to use, modify, and self-host Immermatch. If you host a modified version, you must release your changes under the same license.
