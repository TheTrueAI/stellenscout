# StellenScout

AI-powered job matching for the European market. Upload your CV, and the app uses Google Gemini to analyze your profile, searches for relevant jobs via Google Jobs, and scores each listing against your skills and experience.

## Features

- **CV Parsing** - Supports PDF, DOCX, Markdown, and plain text
- **AI Profile Extraction** - Gemini analyzes your CV to extract skills, experience, languages, and more
- **Smart Search** - Generates optimized search queries in English and local languages
- **Job Scoring** - Each job is scored 0-100 against your profile with detailed reasoning
- **European Market Focus** - Accounts for local language requirements, location keywords, and market norms
- **Caching** - Intelligent caching minimizes API calls across sessions

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
pip install -e ".[ui]"
```

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
# Edit .env with your keys
```

### Run the Streamlit App

```bash
streamlit run stellenscout/app.py
```

### Run the CLI

```bash
stellenscout path/to/your-cv.pdf --location "Munich, Germany"
stellenscout path/to/your-cv.pdf --location "Paris, France"
```

## How It Works

The app uses three AI agent personas powered by Gemini:

1. **The Profiler** - Extracts a structured candidate profile from raw CV text
2. **The Headhunter** - Generates optimized job search queries based on the profile
3. **The Screener** - Evaluates each job listing against the candidate profile (0-100 score)

Jobs are fetched from Google Jobs via SerpApi, deduplicated, and scored in parallel.

## Project Structure

```
stellenscout/
  app.py              # Streamlit web UI
  main.py             # CLI entry point
  llm.py              # Gemini client and retry logic
  cv_parser.py        # CV text extraction (PDF/DOCX/MD/TXT)
  search_agent.py     # Profile extraction and job search
  evaluator_agent.py  # Job scoring
  models.py           # Pydantic data models
  cache.py            # JSON-based result caching
```

## License

MIT
