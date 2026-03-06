Use the Search/API specialist mode for this request.

Environment note:
- No manual virtualenv activation is needed for Makefile targets (`make check`, `make test`, etc.); the Makefile handles it.
- Only activate `.venv` manually for direct Python/pip commands run outside Make targets.
- For formatting, use `make format` (do not run direct `ruff format ...` commands).

Required context order:
1) docs/search-api/AGENT.md (includes active roadmap items R2, R4, R5, R12)
2) docs/search-api/Improving Job Search API Results.md
3) AGENTS.md (search architecture sections with planned-change annotations)

Output requirements:
- Focus only on search/API execution details (provider behavior, relevance quality, stale-link mitigation, routing, pagination, deduplication).
- If strategy tradeoffs are needed, include a brief "Strategy impact" subsection and keep execution recommendations primary.
- Prefer concrete implementation steps over generic advice.
- For implementation tasks, validate with Makefile targets, defaulting to:
	- `make check`
