## What and why

Closes #

## Checks

- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest` (100% line and branch coverage)
- [ ] New or changed write tools use `@require_write_consent` and have tests for accept, decline, cancel and read-only refusal
- [ ] No tokens, account numbers, transaction data, personal emails or private host names in code, fixtures, docs or this description
