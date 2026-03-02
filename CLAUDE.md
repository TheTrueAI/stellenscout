# Immermatch — Agent Quick Reference

## Environment

```bash
source .venv/bin/activate   # ALWAYS required before any command
```

- Python 3.10+, all dependencies in `.venv`
- Gemini model: `gemini-3-flash-preview` via `google-genai` (NOT `google.generativeai`)

## After every code change — run automatically, don't ask

```bash
make check
```

Prefer Makefile targets for daily workflow:
- `make check` (full gate)
- `make test` (tests only)
- `make lint` (ruff lint/format check)
- `make typecheck` (mypy)
- `make run` (Streamlit)
- `make coverage` (coverage report)

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

## Topic routing (specialist docs)

- Search/API/provider questions → consult `docs/search-api/AGENT.md` first.
- Strategy/roadmap/market questions → consult `docs/strategy/AGENT.md` first.
- Cross-domain questions → consult both and split output into execution vs prioritization.
- Apply routing automatically by keyword even if the prompt does not reference doc paths.
- If intent is ambiguous, consult both docs and explicitly label sections.

## Architecture (at a glance)

| Module | Purpose |
|---|---|
| `app.py` | Streamlit UI: CV upload → profile → search → evaluate → display |
| `cv_parser.py` | Extract text from PDF/DOCX/MD/TXT |
| `llm.py` | Gemini API wrapper with retry/backoff |
| `search_api/search_agent.py` | Generate search queries (LLM) + orchestrate search |
| `search_api/search_provider.py` | `SearchProvider` protocol + `get_provider()` factory |
| `search_api/bundesagentur.py` | Bundesagentur für Arbeit job search API provider |
| `search_api/serpapi_provider.py` | Google Jobs via SerpApi provider (future non-DE markets) |
| `evaluator_agent.py` | Score jobs against candidate profile (LLM) + career summary |
| `models.py` | All Pydantic schemas (`CandidateProfile`, `JobListing`, etc.) |
| `cache.py` | JSON file cache in `.immermatch_cache/` |
| `db.py` | Supabase/Postgres: subscribers, jobs, sent-logs |
| `emailer.py` | Resend: verification, welcome, daily digest emails |
| `daily_task.py` | Cron: per-subscriber search → evaluate → email digest |

## Full architecture docs

See `AGENTS.md` for complete system documentation: agent prompts, Pydantic schemas,
DB schema, email flows, caching strategy, and development workflow.
