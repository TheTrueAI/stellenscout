# Copilot Instructions for Immermatch

## Environment

- **Always** activate the virtual environment first: `source .venv/bin/activate`
- Python 3.10+, all dependencies installed in `.venv`
- Gemini model: `gemini-3-flash-preview` via `google-genai` package (NOT the deprecated `google.generativeai`)

## After every code change

Run the full check suite without asking — just do it:

```bash
source .venv/bin/activate && pytest tests/ -x -q && ruff check --fix . && ruff format --check . && mypy .
```

## Testing conventions

- **Framework:** pytest + pytest-cov
- **Test file naming:** `tests/test_<module>.py` for `immermatch/<module>.py`
- **Mock all external services** (Gemini API, SerpAPI, Supabase, Resend) — no API keys needed to run tests
- **Shared fixtures** in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- **Test fixture files** (sample CVs) live in `tests/fixtures/`
- Pydantic models live in `immermatch/models.py` — follow existing patterns
- Prefer external libraries and builtins over custom code

## Code conventions

- All DB writes use `get_admin_client()`, never the anon client
- Log subscriber UUIDs, never email addresses
- All `st.error()` calls show generic messages; real exceptions go to `logger.exception()`

## Architecture at a glance

| Module | Purpose |
|---|---|
| `app.py` | Streamlit UI: CV upload → profile → search → evaluate → display |
| `cv_parser.py` | Extract text from PDF/DOCX/MD/TXT |
| `llm.py` | Gemini API wrapper with retry/backoff |
| `search_agent.py` | Generate search queries (LLM) + orchestrate search |
| `search_provider.py` | `SearchProvider` protocol + `get_provider()` factory |
| `bundesagentur.py` | Bundesagentur für Arbeit API provider (default) |
| `evaluator_agent.py` | Score jobs against profile (LLM) + career summary |
| `models.py` | All Pydantic schemas (`CandidateProfile`, `JobListing`, etc.) |
| `cache.py` | JSON file cache in `.immermatch_cache/` |
| `db.py` | Supabase: subscribers, jobs, sent-logs |
| `emailer.py` | Resend: verification, welcome, daily digest emails |
| `daily_task.py` | Cron: per-subscriber search → evaluate → email |

See `AGENTS.md` for full architecture: agent prompts, DB schema, email flows, caching.
