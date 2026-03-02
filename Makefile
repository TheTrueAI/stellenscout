.PHONY: check test lint coverage format typecheck run install install-dev clean

SHELL := /bin/bash

## Run the full check suite (test + lint + format + typecheck)
check:
	source .venv/bin/activate && pytest tests/ -x -q && ruff check --fix . && ruff format --check . && mypy .

## Run tests only
test:
	source .venv/bin/activate && pytest tests/ -x -q

## Run tests with coverage
coverage:
	source .venv/bin/activate && pytest tests/ --cov=immermatch --cov-report=term-missing

## Lint with ruff (auto-fix)
lint:
	source .venv/bin/activate && ruff check --fix .

## Format with ruff
format:
	source .venv/bin/activate && ruff format .

## Type check with mypy
typecheck:
	source .venv/bin/activate && mypy .

## Run the Streamlit app locally
run:
	source .venv/bin/activate && streamlit run immermatch/app.py

## Install runtime dependencies
install:
	python -m venv .venv
	source .venv/bin/activate && pip install -e .

## Install all dependencies (runtime + test + dev + pre-commit hooks)
install-dev:
	python -m venv .venv
	source .venv/bin/activate && pip install -e ".[dev,test]" && pre-commit install --hook-type pre-commit --hook-type pre-push

## Remove build artifacts and caches
clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage build dist *.egg-info __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
