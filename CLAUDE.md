# Immermatch — Agent Quick Reference

## Environment

```bash
source .venv/bin/activate   # ALWAYS required before any command
```

- Python 3.10+, all dependencies in `.venv`
- Gemini model: `gemini-3-flash-preview` via `google-genai` (NOT `google.generativeai`)

## After every code change — run automatically, don't ask

```bash
source .venv/bin/activate && pytest tests/ -x -q && ruff check --fix . && ruff format --check . && mypy .
```

## Rules

- Mock ALL external services in tests (Gemini, SerpAPI, Supabase, Resend) — no API keys needed
- DB writes: `get_admin_client()` only, never the anon client
- Log subscriber UUIDs, never email addresses
- `st.error()` = generic user messages; `logger.exception()` = real errors
- Pydantic models live in `immermatch/models.py` — follow existing patterns
- Test naming: `tests/test_<module>.py` for `immermatch/<module>.py`
- Shared fixtures in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- Test fixture files (sample CVs) in `tests/fixtures/`
- Prefer external libraries and builtins over custom code

## Architecture (at a glance)

| Module | Purpose |
|---|---|
| `app.py` | Streamlit UI: CV upload → profile → search → evaluate → display |
| `cv_parser.py` | Extract text from PDF/DOCX/MD/TXT |
| `llm.py` | Gemini API wrapper with retry/backoff |
| `search_agent.py` | Generate search queries (LLM) + orchestrate search |
| `search_provider.py` | `SearchProvider` protocol + `get_provider()` factory |
| `bundesagentur.py` | Bundesagentur für Arbeit job search API provider |
| `serpapi_provider.py` | Google Jobs via SerpApi provider (future non-DE markets) |
| `evaluator_agent.py` | Score jobs against candidate profile (LLM) + career summary |
| `models.py` | All Pydantic schemas (`CandidateProfile`, `JobListing`, etc.) |
| `cache.py` | JSON file cache in `.immermatch_cache/` |
| `db.py` | Supabase/Postgres: subscribers, jobs, sent-logs |
| `emailer.py` | Resend: verification, welcome, daily digest emails |
| `daily_task.py` | Cron: per-subscriber search → evaluate → email digest |

## Full architecture docs

See `AGENTS.md` for complete system documentation: agent prompts, Pydantic schemas,
DB schema, email flows, caching strategy, and development workflow.
