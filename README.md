# StellenScout

AI-powered job matching for the European market. Upload your CV, and the app uses Google Gemini to analyze your profile, searches for relevant jobs via Google Jobs, and scores each listing against your skills and experience.

## Features

- **CV Parsing** — Supports PDF, DOCX, Markdown, and plain text
- **AI Profile Extraction** — Gemini analyzes your CV to extract skills, experience, languages, and more
- **Smart Search** — Generates optimized search queries in English and local languages
- **Job Scoring** — Each job is scored 0–100 against your profile with detailed reasoning
- **European Market Focus** — Accounts for local language requirements, location keywords, and market norms
- **Daily Digest** — Subscribe for daily email digests with new AI-matched jobs
- **Caching** — Intelligent caching minimizes API calls across sessions

## Quick Start

### Prerequisites

- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com/app/apikey) API key (for Gemini)
- A [SerpApi](https://serpapi.com/) API key (for Google Jobs search)

### Setup

```bash
git clone https://github.com/<your-username>/stellenscout.git
cd stellenscout
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
streamlit run stellenscout/app.py
```

## How It Works

The app uses four AI agent personas powered by Gemini:

1. **The Profiler** — Extracts a structured candidate profile from raw CV text
2. **The Headhunter** — Generates optimized job search queries based on the profile
3. **The Screener** — Evaluates each job listing against the candidate profile (0–100 score)
4. **The Advisor** — Generates a career summary with market insights and skill gap analysis

Jobs are fetched from Google Jobs via SerpApi, deduplicated, and scored in parallel.

## Project Structure

```
stellenscout/
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
```

## License

AGPL-3.0 License
