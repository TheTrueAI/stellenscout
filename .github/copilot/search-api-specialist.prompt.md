Use the Search/API specialist mode for this request.

Required context order:
1) docs/search-api/AGENT.md
2) docs/search-api/Improving Job Search API Results.md
3) AGENTS.md (search architecture sections)

Output requirements:
- Focus only on search/API execution details (provider behavior, relevance quality, stale-link mitigation, routing, pagination, deduplication).
- If strategy tradeoffs are needed, include a brief "Strategy impact" subsection and keep execution recommendations primary.
- Prefer concrete implementation steps over generic advice.
- For implementation tasks, validate with Makefile targets, defaulting to:
	- `make check`
