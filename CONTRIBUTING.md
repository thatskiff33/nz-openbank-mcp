# Contributing

Thanks for helping. Bug reports and pull requests are welcome; for anything
security-related, follow [SECURITY.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/SECURITY.md)
instead of opening a public issue.

## Set up

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync --extra dev
uv run nz-openbank-mcp     # stdio server from your checkout
```

Python 3.14 or newer is required.

## Checks

Every pull request must pass these; CI runs them along with bandit and a
test run on the next Python release:

```bash
uv run pytest                                   # tests, 100% line and branch coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy src                                 # strict
uv export --frozen --no-emit-project --all-extras --format requirements-txt \
  | uv run pip-audit --strict --disable-pip --require-hashes -r /dev/stdin
uv run --no-project python scripts/sync_plugin_manifests.py --check
uv run --no-project python scripts/check_packaging.py   # version lockstep, package contents
uv run --no-project python scripts/check_md_links.py    # repo-relative Markdown links resolve
```

Coverage is a hard gate: a change that leaves any line or branch untested
fails. Add tests with the code, using the fixtures in `tests/conftest.py`.
Fixtures and examples must be synthetic: no real tokens, account numbers,
transactions, names or email addresses.

## Changing the code

- Tools are thin wrappers over Akahu Personal App endpoints. Analysis such as
  budgets or spending reports is left to the calling model, so new tools
  should fetch, format or trigger, not interpret.
- Write tools use `@require_write_consent` and must show every value they send
  in the confirmation prompt (`describe_request`).
- A tool's output shape goes in the docstring body, before `Args:`.
- [AGENTS.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/AGENTS.md) has the code map
  and the rules for tools, write safety, configuration and tests.

## Plugin manifests and versions

The host plugin manifests under `plugin/`, the root marketplace indexes
(`.claude-plugin/`, `.agents/plugins/`, `.cursor-plugin/`, `.grok-plugin/`)
and `mcpb/manifest.json` are generated from `plugin/plugin.base.toml`. Edit
that file, then run
`uv run --no-project python scripts/sync_plugin_manifests.py` and commit the
result.

The version lives in two places that must match: `version` in
`pyproject.toml` and `__version__` in `src/nz_openbank_mcp/__init__.py`
(`check_packaging.py` enforces this). The sync script copies it into every
manifest. Releases are cut by the
maintainer; see [PUBLISHING.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/PUBLISHING.md).

## Style

Plain, specific writing in code, comments, commits and docs: no emojis and no
em dashes. Comments explain why, not what.
