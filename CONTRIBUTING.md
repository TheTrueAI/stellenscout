# Contributing to Immermatch

Thanks for your interest in contributing! This guide covers setup, conventions, and the PR process.

## Development Setup

### Prerequisites

- Python 3.10+
- Git

### Installation

```bash
git clone https://github.com/TheTrueAI/immermatch.git
cd immermatch
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,test]"
pre-commit install --hook-type pre-commit --hook-type pre-push
```

No API keys are needed for running tests — all external services are mocked.

## Development Workflow

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes and run quality checks:
   ```bash
   ruff check . && ruff format --check .
   mypy immermatch/ daily_task.py
   pytest tests/ -x -q
   ```

3. Commit your changes. Pre-commit hooks will automatically run:
   - Trailing whitespace / end-of-file fixes
   - YAML, TOML, JSON validation
   - Secret detection (`detect-secrets`)
   - Linting and formatting (`ruff`)
   - Type checking (`mypy`)

4. Push your branch. The pre-push hook runs the full test suite.

5. Open a pull request against `main`.

## Code Style

- **Formatter / Linter:** [Ruff](https://docs.astral.sh/ruff/) — line length 120, rules: E, F, W, I, UP
- **Type checking:** [mypy](https://mypy-lang.org/) with `ignore_missing_imports = true`
- **Python version:** Target 3.10+ (use `from __future__ import annotations` patterns sparingly; prefer `X | Y` union syntax)

## Testing Conventions

- **Framework:** pytest + pytest-cov
- **All external services must be mocked** — Gemini, SerpApi, Supabase, and Resend should never be called in tests
- **Shared fixtures** are in `tests/conftest.py`: `sample_profile`, `sample_job`, `sample_evaluation`, `sample_evaluated_job`
- **Test fixture files** (sample CVs, etc.) go in `tests/fixtures/`
- **File naming:** `tests/test_<module>.py` for `immermatch/<module>.py`
- **Pydantic models** live in `immermatch/models.py` — follow existing patterns

## Project Conventions

- All DB writes use the admin client (`get_admin_client()`), never the anon client
- Log subscriber UUIDs, never email addresses
- All `st.error()` calls must show generic user-facing messages; real exceptions go to `logger.exception()`
- Use the `google-genai` package (not the deprecated `google.generativeai`)

## Pull Request Guidelines

- Use a descriptive title (e.g., `feat: add job expiry badge`, `fix: handle empty search results`)
- Link to a related issue if one exists
- All CI checks must pass (lint, types, tests)
- PRs are squash-merged into `main`

## Reporting Issues

- Search [existing issues](https://github.com/TheTrueAI/immermatch/issues) first
- Use the provided issue templates (bug report, feature request, question)
- For bugs: include steps to reproduce, expected vs actual behavior, and your environment (Python version, OS)

## Code of Conduct

Be respectful and constructive. We follow the spirit of the [Contributor Covenant](https://www.contributor-covenant.org/) — harassment, discrimination, and bad-faith behavior are not tolerated.
