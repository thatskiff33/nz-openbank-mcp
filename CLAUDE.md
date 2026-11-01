# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Unofficial MCP server for the Akahu open-finance API (NZ). Ships **14 tools** as
thin wrappers over Akahu Personal-App endpoints, distributed as
`nz-openbank-mcp`. Runs locally over stdio; no hosted backend.

Design line: **primitives only.** Analytical questions ("what did I spend on
groceries?", "which subscriptions am I paying?") are the LLM's job over raw
transaction data. Don't add analytical/forecasting tools.

## Commands

All commands use `uv`.

```bash
uv sync --extra dev                    # install incl. dev deps
uv run pytest                          # full suite, 100% line+branch coverage gate
uv run pytest tests/test_accounts.py::test_list_accounts_returns_masked  # one test
uv run pytest -k "currency"            # filter by name
uv run ruff check .                    # lint (must be clean)
uv run mypy src                        # strict-mode type check (must be clean)
uv export --frozen --no-emit-project --all-extras --format requirements-txt \
  | uv run pip-audit --strict --disable-pip --require-hashes -r /dev/stdin  # audit the lock
uv build                               # sdist + wheel into dist/
uv run nz-openbank-mcp                    # run server over stdio from local checkout
FASTMCP_ENV_FILE=/dev/null uv run fastmcp dev src/nz_openbank_mcp/server.py  # FastMCP inspector
```

The pytest config (`pyproject.toml [tool.pytest.ini_options]`) enforces
`--cov-fail-under=100` on **line AND branch** coverage. Any patch that drops
coverage below 100% fails the build. Mypy runs in `strict` mode. A
`DeprecationWarning` raised from `nz_openbank_mcp` or `tests` fails the suite.

Python is 3.14+. Runtime dependencies carry major-version caps because `uvx`
ignores `uv.lock` and resolves fresh on every launch; `sse-starlette!=3.4.6`
excludes a known-bad transitive release.

## CI

`.github/workflows/ci.yml` runs on PRs, pushes to `main`, weekly, and on
manual dispatch. A `changes` job path-filters PRs so only the affected jobs run
(lint, types, test on 3.14 and 3.15, audit, workflow-lint, packaging, docs);
`main`, scheduled and manual runs force every job. The single `ci-ok` job is
the only required check and passes when each job succeeded or was skipped.
PR runs cancel stale runs; `main` runs are never cancelled. Branch protection
does not require PRs to be up to date with `main`.

```bash
uv run ruff format --check .                     # formatting (enforced in CI)
uv run --no-project python scripts/check_packaging.py  # manifests + version lockstep
uv run --no-project python scripts/check_md_links.py   # repo-relative Markdown links
uvx --from actionlint-py==1.7.12.25 actionlint && uvx zizmor==1.31.1 --offline .github/
```

`release.yml` runs only on `release: published` and refuses to build unless
the tagged commit is on `main` and has a successful `ci.yml` push run there. Actions are pinned to full
commit SHAs; Dependabot (`.github/dependabot.yml`) proposes weekly grouped
updates for Actions and uv.

## Architecture

```
src/nz_openbank_mcp/
├── server.py        Root FastMCP server; mounts 3 sub-servers under namespaces
├── tools/
│   ├── accounts.py        6 tools (4 read, 2 write) under acct/* namespace
│   ├── transactions.py    6 tools (5 read, 1 write) under txn/* namespace
│   └── identity.py        2 tools (1 read, 1 write) under id/* namespace
├── client.py        AkahuClient: httpx async client + 3-attempt retry/backoff
├── models.py        Pydantic shapes; aliases handle Akahu's _id / _account fields
├── config.py        AkahuConfig (pydantic-settings, env_prefix="AKAHU_"); no implicit .env
├── deps.py          Process-wide AkahuClient cache (get_client / aclose_client)
├── safety.py        @require_write_consent decorator + 3-layer safety
└── formatting.py    format_money, mask_account, parse_iso_date
```

### Sub-server mount pattern

Each tool group is its own `FastMCP("name")` instance defined inside `tools/`,
then mounted at the root in `server.py` via `mcp.mount(sub.server, namespace="...")`.
Tools end up exposed as `<namespace>_<tool>` (e.g. `acct_list_accounts`).
Adding a new tool means adding `@server.tool` inside one of the existing sub-server
modules; adding a new sub-server means a new file under `tools/` and one
`mcp.mount(...)` line in `server.py`.

### Three-layer write safety

Every write tool is decorated with `@require_write_consent("...", automatable=...)`.
The decorator (in `safety.py`) enforces:

1. **Read-only refusal.** `AKAHU_READ_ONLY=true` (default) raises `ReadOnlyError`
   before any HTTP call.
2. **Per-call elicitation.** Calls `ctx.elicit()` for user confirmation. Decline
   or cancel raises `ElicitationDeclinedError`.
3. **Automation bypass.** If the decorator was called with `automatable=True`
   AND `AKAHU_AUTOMATION_BYPASS=true`, layer 2 is skipped (still logs at INFO).

Layer 2 depends on the negotiated MCP protocol. Handshake-era connections
(2025-11-25 and earlier) get a server-initiated `ctx.elicit()`. 2026-07-28
connections have no server-initiated requests, so the tool returns an
`InputRequiredResult` with a single-use nonce in `request_state` and runs only
when the client retries with an accept answer and that nonce. Mid-call value
prompts (`elicit_value`) fail on 2026-07-28 connections; pass the value as an
argument instead. `tests/test_consent_e2e.py` covers both eras through a real
`fastmcp.Client`.

`bypass_eligible_tools()` is the runtime registry consulted by the startup
banner. `AKAHU_READ_ONLY=true` + `AKAHU_AUTOMATION_BYPASS=true` is rejected at
startup by `AkahuConfig._reject_incoherent_bypass`.

When adding a new write tool, prefer `automatable=False` unless the action is
genuinely idempotent, rate-limited, and free of third-party side effects.

## FastMCP docstring parsing (important)

FastMCP parses Google-style docstrings (`Args:` blocks) into the per-parameter
JSON schema for `tools/list`. But the **`Returns:` block is silently dropped**
from the tool description whenever an `Args:` block is also present. So output
shape documentation must live in the *body paragraph* of the docstring (between
the summary line and the `Args:` block), not in a `Returns:` section.

Established pattern across all 14 tools:

```python
"""Summary line.

Returns {"key": ...} prose describing output shape and any usage context.

Args:
    foo: ...
    bar: ...
"""
```

Verify with: `uv run python -c 'import asyncio; from nz_openbank_mcp.server import build_server; m=build_server(); [print(t.name, ":", t.description) for t in asyncio.run(m.list_tools())]'`.

## Akahu API constraints

- **Configuration comes from the process environment.** No settings class
  reads a working-directory `.env`; an env file loads only when
  `AKAHU_ENV_FILE` names an absolute path. `base_url` must be on
  `https://api.akahu.io` unless `AKAHU_ALLOW_CUSTOM_BASE_URL=true` is a real
  environment variable (never honoured from a file). Tokens are `SecretStr`;
  unwrap with `get_secret_value()` only where headers are built.
- **Personal Apps only.** Akahu's Personal-Apps doc states verbatim:
  "App-scoped endpoints are not available to Personal Apps." In scope:
  `/categories`, `/categories/{id}`, `/connections`, `/connections/{id}`,
  `/parties`, `/parties/{code}`, `/identity/{id}/verify-name`. All 403 from
  a Personal-App token. Do not add tools for them. Webhooks and Payments
  are likewise blocked for Personal Apps per the same doc.
- **Two-header auth.** Every request needs `Authorization: Bearer <user_token>`
  and `X-Akahu-Id: <app_token>`. Handled centrally by `AkahuClient`.
- **`Transaction` has no per-transaction currency.** Transactions are formatted
  in NZD (`format_money(amount, "NZD")`). For multi-currency accounts (e.g.
  Wise PHP/USD/EUR), callers must pair the result with `accounts/get_account`
  to read the parent account's currency. This is documented in
  `transactions._summarise`.
- **`format_money(amount, currency="NZD")`**: NZD renders with `$` symbol;
  any other ISO code renders as `<CODE> 1,234.56` (e.g. `USD 100.00`); empty
  currency falls back to NZD.
- **Account numbers are masked** via `mask_account`, preserving the bank code,
  suffix, and final four account digits. All tools surfacing accounts must use
  it.

## Testing patterns

- `tests/conftest.py` provides three env fixtures: `fake_env` (read-only,
  default), `writable_env` (writes enabled, every write elicits), `bypass_env`
  (writes enabled, automatable writes skip elicit).
- `ctx_factory()` from conftest builds a mock FastMCP `Context` whose `elicit()`
  resolves to `"accept"` | `"decline"` | `"cancel"`. Used to test all three
  outcomes of every write tool.
- HTTP traffic is intercepted with `respx_mock` (base_url scoped to Akahu).
- `load_fixture("name")` reads `tests/fixtures/name.json`.
- Tests for tool modules typically patch `deps.get_client` to inject a
  `MagicMock` with `AsyncMock` methods (see `_fake_client()` in
  `test_accounts.py`).

When adding a new tool, follow the existing pattern: cover the happy path,
empty/None edge cases, and (for writes) all three elicit outcomes plus
read-only refusal.

## Distribution

Three channels, same code:

1. **Python package** on PyPI (`uvx nz-openbank-mcp`) - works in any MCP
   host. The package source is `src/nz_openbank_mcp/`.
2. **Claude Code marketplace plugin** (`/plugin marketplace add thatskiff33/nz-openbank-mcp`) -
   this repo is its own marketplace via `.claude-plugin/marketplace.json`,
   which points at the plugin files in `plugin/`. **Claude Code only** -
   Claude Desktop has no UI to set marketplace-plugin `userConfig` values
   (anthropics/claude-code#39455, #39827).
3. **Claude Desktop Extension (.mcpb)** - delivery wrapper around the same
   package for Claude Desktop. Overlay files live at `mcpb/` inside this
   repo; the bundle is packed by CI and attached to each GitHub Release as
   `nz-openbank-mcp-X.Y.Z.mcpb`.

The Claude Code plugin overlay is **three files**:

- `plugin/.claude-plugin/plugin.json` - manifest. Declares `userConfig` for
  the two Akahu tokens (`sensitive: true`) and the two safety flags (defaults
  preserve the read-only/no-bypass posture).
- `plugin/.mcp.json` - launch spec. Runs the package via `uvx` and injects each
  `userConfig` value into the matching `AKAHU_*` env var via
  `${user_config.KEY}` substitution. The package's pydantic-settings
  layer reads those env vars exactly as it does outside the plugin.
- `plugin/README.md` - end-user install/setup notes for the marketplace path.

The Desktop Extension overlay is **three files** under `mcpb/`:

- `mcpb/manifest.json` - MCPB spec v0.3 manifest. Mirrors the plugin manifest
  but uses snake_case `user_config` and nests the launch spec under
  `server.mcp_config` (same `uvx` invocation, same
  `${user_config.KEY}` env substitution).
- `mcpb/.mcpbignore` - excludes `*.md` from the packed bundle.
- `mcpb/README.md` - short developer-facing note. End-user install docs live
  in the main `README.md`.

The two plugin systems use **different naming conventions**: marketplace
plugins use `userConfig` (camelCase) at the top level of `plugin.json`;
Desktop Extensions use `user_config` (snake_case) at the top level of
`manifest.json`. The `${user_config.KEY}` substitution syntax inside env
blocks is identical across both.

Credential UX: both paths prompt at install, store secrets in the OS
keychain (macOS Keychain on macOS, Windows Credential Manager on Windows),
and re-inject them at MCP launch. No shell env, no `.env`, no wrapper
script. Adding a new env-configurable knob means **three coordinated
edits**: a `userConfig` entry in `plugin/.claude-plugin/plugin.json`, a
matching `${user_config.KEY}` line in `plugin/.mcp.json`, AND a parallel
`user_config` entry plus `server.mcp_config.env` line in `mcpb/manifest.json`.

The repo root must stay free of `.mcp.json` (it would conflict with
project-scope auto-detection when developing locally). The `.gitignore`
rule `/.mcp.json` is anchored to root so the plugin's file at
`plugin/.mcp.json` stays tracked.

Release flow is documented in `PUBLISHING.md`. Summary: bump the version in
`pyproject.toml`, `plugin/.claude-plugin/plugin.json` and `mcpb/manifest.json`
plus the `nz-openbank-mcp==X.Y.Z` launch pins in `plugin/.mcp.json` and
`mcpb/manifest.json` (`scripts/check_packaging.py` enforces all five). Merge,
tag the merge commit `vX.Y.Z`, run `gh workflow run release.yml --ref vX.Y.Z`
for the TestPyPI dry run, then publish the GitHub Release and approve the
`pypi` environment. `ci-gate` requires a green `ci.yml` push run on `main`
for the tagged commit. Trusted Publishing (OIDC) handles PyPI and TestPyPI;
`GITHUB_TOKEN` attaches the wheel, sdist and `.mcpb` to the Release.

## Style conventions (from user's global instructions)

- **No emojis** in code, comments, commit messages, or documentation.
- **No em dashes (`—`)** in writing; use hyphens (`-`) or restructure sentences.
- **Humble language**: avoid claiming "success" without verification. Use
  "Implemented X, ready for testing" rather than "Successfully implemented X".
- **Comments explain WHY**, not WHAT. Default to no comments.
- **Review before changing**: when asked to review or analyze, do that first
  and report findings before making changes.

## Sub-agent style note

When working in this repo, the user has expressed preference for tight,
spec-style docstrings/comments and is allergic to decisioning history,
audit-trail prose, and roadmap chatter in permanent docs. Keep docs functional
("what it does, how to use it"), not retrospective ("why we picked this over X").
