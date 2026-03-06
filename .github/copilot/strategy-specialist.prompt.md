Use the Strategy specialist mode for this request.

Environment note:
- No manual virtualenv activation is needed for Makefile targets (`make check`, `make test`, etc.); the Makefile handles it.
- Only activate `.venv` manually for direct Python/pip commands run outside Make targets.
- For formatting, use `make format` (do not run direct `ruff format ...` commands).

Required context order:
1) docs/strategy/AGENT.md (includes active execution set and KPI targets)
2) docs/strategy/ROADMAP.md (step-by-step plans, R1-R12)
3) AGENTS.md (architecture sections with planned-change annotations)

Output requirements:
- Focus on prioritization, sequencing, launch/monetization tradeoffs, and KPI impact.
- Separate recommendations into:
  1) Immediate next actions (1-2 weeks)
  2) Medium-term bets (1-3 months)
- Keep implementation-level API detail out unless explicitly requested.
- If strategy recommendations include code changes, validate with:
  - `make check`
