# Search API Specialist Agent

## Mission
Maintain and improve search quality, freshness, and provider reliability for Immermatch job discovery.

## Environment
- No manual virtualenv activation is needed when using Makefile targets (`make check`, `make test`, etc.); the Makefile handles it.
- Activate `.venv` manually only for direct Python/pip commands run outside Make targets.

## Canonical Code Scope
- `immermatch/search_api/search_provider.py`
- `immermatch/search_api/search_agent.py`
- `immermatch/search_api/serpapi_provider.py`
- `immermatch/search_api/bundesagentur.py`
- `immermatch/search_api/link_validator.py`
- `immermatch/search_api/blocked_portals.txt`
- `immermatch/search_api/_constants.py`

## Current Architecture Decisions
- Default provider is Bundesagentur fur Arbeit (verified German listings).
- SerpApi provider is optional and enabled only when `SERPAPI_KEY` is set.
- Combined provider mode merges BA + SerpApi when SerpApi is configured.
- Search orchestration deduplicates by `title|company_name|location`.
- Provider quotas in combined mode enforce source diversity (`_MIN_JOBS_PER_PROVIDER`).
- **Reliability badges** classify each listing as `verified` (Bundesagentur), `aggregator` (known job boards), or `unverified` (unknown source). Rendered as coloured badges on job cards.
- **Blocked portal list** is externalized to `blocked_portals.txt` (one domain per line, `#` comments).
- **Trusted portal list** (`_TRUSTED_PORTALS` in serpapi_provider) promotes known job boards and ATS platforms (LinkedIn, StepStone, Softgarden, etc.) to `aggregator` reliability.
- **Staleness filtering** works in two layers: `chips=date_posted:week` at SerpAPI query level, and `_is_stale()` as defense-in-depth for listings >14 days old.
- **Link validation** (`link_validator.py`) runs concurrent HEAD requests after search to drop dead links (404/410/403) and redirect-to-homepage patterns. Only checks non-verified listings.

## Active Roadmap Items (Search-Relevant)

These items from `docs/strategy/ROADMAP.md` directly affect search code:

### R2 — Canonical location aliases (#66) [Week 1]
- Normalize `Koln/Cologne`, `Munchen/Munich` at input boundary before query generation and provider calls.
- Normalized value must be consistent in cache keys, provider calls, and logs.
- Affects: `search_agent.py` (query generation), cache keying, provider `.search()` location param.

### R4 — Wrong-city carryover (#70) [Week 1]
- Consecutive city searches in one session can show mixed-city results.
- Root cause likely in cache keying, session state, or rendering pipeline carrying stale results.
- Affects: `cache.py` (keying), `search_agent.py` (result containers), `app.py` (rendering).

### R5 — BA homepage-link filtering (#40) [Week 2]
- BA listings sometimes include useless homepage links (`https://www.arbeitsagentur.de/`).
- Filter non-actionable links (homepage-only, generic landing redirects) in BA parsing path.
- Preserve valid alternative links when one option is filtered.
- Affects: `bundesagentur.py` (parsing/link construction).

### R12 — Replace file-based cache with DB-backed storage [Week 3]
- Current `ResultCache` in `cache.py` uses filesystem JSON — breaks on multi-instance deploys.
- Planned: DB tables or key-value storage with proper TTL and per-user isolation.
- New backend behind existing `ResultCache` interface for minimal disruption.

## Known Tradeoffs
- BA gives higher listing trust; SerpApi increases breadth at higher noise risk.
- Portal blocklist removes common low-quality aggregators but may drop occasional valid listings.
- Link validation adds latency (~1-3s with concurrent HEAD requests) but prevents dead links from reaching users.
- Reliability classification uses domain-level matching on `urlparse().netloc`, not full URL substring — more precise but requires exact domain keywords in the trusted/blocked lists.

## Feedback Loop
- `scripts/label_reliability.py` extracts SerpAPI jobs from cache for manual labelling.
- `scripts/analyze_labels.py` computes accuracy and suggests domain additions.
- Labels stored in `immermatch/search_api/reliability_labels.jsonl` (JSONL, one entry per job).

## Research Inputs
- `docs/search-api/Improving Job Search API Results.md`

## Validation Workflow
- Prefer Makefile targets for checks:
	- `make check` (full gate)
	- `make test` (tests)
	- `make lint` (ruff)
	- `make format` (format code; prefer this over direct `ruff format ...` commands)
	- `make typecheck` (mypy)

## Decision Log Template
Use this format for each change:
- Date:
- Decision:
- Context:
- Alternatives considered:
- Impact:
- Follow-up tasks:
