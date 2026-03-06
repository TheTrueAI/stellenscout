# Immermatch — Agent Quick Reference

## Environment

```bash
# No manual activation needed for Makefile targets (`make check`, `make test`, etc.).
# Activate `.venv` only when running direct Python/pip commands outside `make`.
```

- Python 3.10+, all dependencies in `.venv`
- Gemini model: `gemini-3.1-flash-lite-preview` via `google-genai` (NOT `google.generativeai`)

## After every code change — run automatically, don't ask

```bash
make check
```

Prefer Makefile targets for daily workflow:
- `make check` (full gate)
- `make test` (tests only)
- `make lint` (ruff lint/format check)
- `make format` (format code; prefer this over direct `ruff format ...` commands)
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

## Active Roadmap (March 2026)

Source of truth: `docs/strategy/ROADMAP.md`. Pick the next unchecked task from there.

Current focus areas (in priority order):
1. Search relevance + location consistency (R1, R2, R3, R4)
2. Link quality + subscription lifecycle (R5, R6, R7)
3. Architecture debt (R8, R11, R12)
4. Growth instrumentation (R9, R10)

Planned architectural changes to be aware of:
- **R11**: Extract `PipelineService` from `app.py` — shared with `daily_task.py`
- **R12**: Replace file-based `ResultCache` with DB-backed storage
- **R8**: Split `confirmation_token` / `manage_token` in DB schema
- **R6**: Unsubscribe = hard-delete subscriber row

## On-demand skills (loaded only when needed)

- **Topic routing**: `.claude/skills/topic-routing.md` — search/API/strategy doc routing
- **Architecture**: `.claude/skills/architecture.md` — module map and full architecture reference
