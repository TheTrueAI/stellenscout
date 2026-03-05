# Copilot Instructions for Immermatch

## Environment

- No manual virtualenv activation is needed when using Makefile targets (`make check`, `make test`, etc.); the Makefile handles it.
- Only activate `.venv` manually for direct Python/pip commands run outside Make targets.
- Python 3.10+, all dependencies installed in `.venv`
- Gemini model: `gemini-3.1-flash-lite-preview` via `google-genai` package (NOT the deprecated `google.generativeai`)

## After every code change

Run the full check suite without asking — just do it:

```bash
make check
```

Prefer Makefile targets for routine workflows:
- `make check` (full gate)
- `make test` (tests)
- `make lint` (ruff)
- `make format` (format code; prefer this over direct `ruff format ...` commands)
- `make typecheck` (mypy)
- `make run` (Streamlit app)
- `make coverage` (coverage report)

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

## Topic routing (specialist agent docs)

When handling prompts, route to the matching specialist doc before answering:

- **Search/API/provider topics** (keywords like: API, search, provider, Bundesagentur, SerpApi, query quality, stale jobs)
	- First consult: `docs/search-api/AGENT.md`
	- Then use supporting context from: `docs/search-api/Improving Job Search API Results.md` and `AGENTS.md`
- **Strategy/roadmap/market topics** (keywords like: strategy, roadmap, prioritization, launch, monetization, pricing, market)
	- First consult: `docs/strategy/AGENT.md`
	- Then use supporting context from: `docs/strategy/ROADMAP.md` and `AGENTS.md`

If a prompt spans both domains, consult both docs and explicitly separate recommendations into:
1) Search/API execution
2) Strategy/prioritization

### Auto-routing behavior

- Apply this routing automatically when the prompt contains matching domain keywords, even if the user does not explicitly reference the doc path.
- If the intent is ambiguous between domains, consult both docs and provide a split response.
- If no domain keywords are present, continue with normal project-wide guidance.

### Trigger keywords (non-exhaustive)

- **Search/API domain:** api, search, provider, bundesagentur, serpapi, stale jobs, query quality, deduplication, routing, pagination
- **Strategy domain:** strategy, roadmap, prioritization, launch, pricing, monetization, market, growth, KPI, positioning

## Architecture at a glance

| Module | Purpose |
|---|---|
| `app.py` | Streamlit UI: CV upload → profile → search → evaluate → display |
| `cv_parser.py` | Extract text from PDF/DOCX/MD/TXT |
| `llm.py` | Gemini API wrapper with retry/backoff |
| `search_api/search_agent.py` | Generate search queries (LLM) + orchestrate search |
| `search_api/search_provider.py` | `SearchProvider` protocol + `get_provider()` factory |
| `search_api/bundesagentur.py` | Bundesagentur für Arbeit API provider (default) |
| `evaluator_agent.py` | Score jobs against profile (LLM) + career summary |
| `models.py` | All Pydantic schemas (`CandidateProfile`, `JobListing`, etc.) |
| `cache.py` | JSON file cache in `.immermatch_cache/` |
| `db.py` | Supabase: subscribers, jobs, sent-logs |
| `emailer.py` | Resend: verification, welcome, daily digest emails |
| `daily_task.py` | Cron: per-subscriber search → evaluate → email |

See `AGENTS.md` for full architecture: agent prompts, DB schema, email flows, caching.
