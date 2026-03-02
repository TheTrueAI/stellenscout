# Search API Specialist Agent

## Mission
Maintain and improve search quality, freshness, and provider reliability for Immermatch job discovery.

## Canonical Code Scope
- `immermatch/search_api/search_provider.py`
- `immermatch/search_api/search_agent.py`
- `immermatch/search_api/serpapi_provider.py`
- `immermatch/search_api/bundesagentur.py`

## Current Architecture Decisions
- Default provider is Bundesagentur für Arbeit (verified German listings).
- SerpApi provider is optional and enabled only when `SERPAPI_KEY` is set.
- Combined provider mode merges BA + SerpApi when SerpApi is configured.
- Search orchestration deduplicates by `title|company_name|location`.
- Provider quotas in combined mode enforce source diversity (`_MIN_JOBS_PER_PROVIDER`).

## Known Tradeoffs
- BA gives higher listing trust; SerpApi increases breadth at higher noise risk.
- Portal blocklist removes common low-quality aggregators but may drop occasional valid listings.
- Temporal freshness currently relies on provider recency filters; no URL HEAD-validation pipeline yet.

## Research Inputs
- `docs/search-api/Improving Job Search API Results.md`

## Decision Log Template
Use this format for each change:
- Date:
- Decision:
- Context:
- Alternatives considered:
- Impact:
- Follow-up tasks:
