# Copilot Instructions for Immermatch

## Environment

- **Always** activate the virtual environment first: `source .venv/bin/activate`
- Python 3.10+, all dependencies installed in `.venv`
- Gemini model: `gemini-3-flash-preview` via `google-genai` package (NOT the deprecated `google.generativeai`)

## After every code change

Run the full check suite without asking — just do it:

```bash
source .venv/bin/activate && pytest tests/ -x -q && ruff check . && mypy .
```

## Testing conventions

- **Framework:** pytest + pytest-cov
- **Test file naming:** `tests/test_<module>.py` for `immermatch/<module>.py`
- **Mock all external services** (Gemini API, SerpAPI, Supabase, Resend) — no API keys needed to run tests
- **Shared fixtures** in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- **Test fixture files** (sample CVs) live in `tests/fixtures/`
- Pydantic models live in `immermatch/models.py` — follow existing patterns

## Code conventions

- All DB writes use `get_admin_client()`, never the anon client
- Log subscriber UUIDs, never email addresses
- All `st.error()` calls show generic messages; real exceptions go to `logger.exception()`
