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

## On-demand skills (loaded only when needed)

- **Topic routing**: `.claude/skills/topic-routing.md` — search/API/strategy doc routing
- **Architecture**: `.claude/skills/architecture.md` — module map and full architecture reference
