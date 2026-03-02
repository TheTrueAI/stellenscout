Fetch and address review comments from the most recent PR on the current branch.

## Execution policy

- Run all `gh` commands (or equivalent GitHub MCP calls) immediately without asking for confirmation.
- Do **not** start code edits until after presenting a full comment assessment and getting explicit user confirmation.

## Workflow

1. **Get the PR number:** `gh pr view --json number --jq .number`
2. **Get review comments:**
   Use the GitHub MCP to fetch PR review comments:
   ```bash
   gh pr view --json reviews --jq '.reviews[] | {author: .author.login, body, state}'
   gh pr view --json comments --jq '.comments[] | {author: .author.login, body, path, line}'
   gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '.[] | {path, line, body, user: .user.login}'
   ```
3. **List all comments first (no edits yet):**
   - Produce a complete checklist of every review comment.
   - For each item include:
     - **Assessment:** valid / duplicate / not applicable
     - **Suggestion:** exact fix you plan to apply (or why you will skip)
4. **Ask for confirmation:**
   - Share the full checklist with the user.
   - Ask for explicit confirmation before implementing any code/document changes.
5. **After confirmation, implement valid changes**, then run the check suite:
   ```bash
   source .venv/bin/activate && pytest tests/ -x -q && ruff check --fix . && ruff format --check . && mypy .
   ```
6. **Commit strategy:**
   - **Trivial fixes** (typos, naming, small refactors): `git add -A && git commit --amend --no-edit && git push --force-with-lease`
   - **Substantive changes** (new tests, logic changes, API modifications): `git add -A && git commit -m "fix: address PR feedback — <summary>" && git push`
7. **NEVER** force-push to `main` or any shared branch — only the current feature branch
