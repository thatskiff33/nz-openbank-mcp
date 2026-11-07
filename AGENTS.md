# AGENTS.md

Working notes for coding agents in this repository.

## Project in one paragraph

`nz-openbank-mcp` is an MCP server that exposes 14 tools over Akahu
Personal App endpoints (NZ open finance). It runs over stdio by default, with
an optional authenticated Streamable HTTP entrypoint (`nz-openbank-mcp-http`).
Tools are primitives: they fetch, format and mask data, or trigger a small set
of writes. Spending analysis, categorising and forecasting belong to the
calling model, so do not add tools for them.

## Checks every change must pass

```bash
uv sync --extra dev
uv run pytest                      # 100% line and branch coverage, enforced
uv run pytest tests/test_accounts.py -k masked   # narrow a run
uv run ruff check . && uv run ruff format --check .
uv run mypy src                    # strict
uv export --frozen --no-emit-project --all-extras --format requirements-txt \
  | uv run pip-audit --strict --disable-pip --require-hashes -r /dev/stdin
uv run --no-project python scripts/sync_plugin_manifests.py --check
uv run --no-project python scripts/check_packaging.py
uv run --no-project python scripts/check_md_links.py
uvx --from actionlint-py==1.7.12.25 actionlint && uvx zizmor==1.31.1 --offline .github/
```

Other useful commands: `uv run nz-openbank-mcp` (stdio server from the
checkout), `FASTMCP_ENV_FILE=/dev/null uv run fastmcp dev
src/nz_openbank_mcp/server.py` (inspector), `uv build`.

On Windows, run `uv run pytest --no-cov` (POSIX-only lines cannot run there;
CI's Linux job enforces coverage), and run the `pip-audit` pipe in Git Bash or
from an exported requirements file.

A `DeprecationWarning` raised from `nz_openbank_mcp` or `tests` fails the
suite. Python is 3.14+; CI also tests 3.15. Runtime dependencies are capped
at the next major version because `uvx` resolves fresh on each launch and
ignores `uv.lock`.

## Code map

| Path | Role |
| --- | --- |
| `src/nz_openbank_mcp/server.py` | Builds the root server, mounts `acct`, `txn` and `id`, prints the safety banner |
| `src/nz_openbank_mcp/tools/accounts.py` | `acct_*`: 4 reads, 2 writes (refreshes) |
| `src/nz_openbank_mcp/tools/transactions.py` | `txn_*`: 5 reads, 1 write (support ticket) |
| `src/nz_openbank_mcp/tools/identity.py` | `id_*`: 1 read, 1 write (name check) |
| `src/nz_openbank_mcp/client.py` | `AkahuClient`: async httpx, both auth headers, retries only idempotent calls, caps paging at `MAX_PAGES` |
| `src/nz_openbank_mcp/models.py` | Pydantic models; aliases map Akahu's `_id` and `_account` |
| `src/nz_openbank_mcp/config.py` | `AkahuConfig` (`AKAHU_*` settings); `get_config()` reads it once per process |
| `src/nz_openbank_mcp/deps.py` | Shared client (`get_client`, `aclose_client`, closed by the root server's lifespan) |
| `src/nz_openbank_mcp/safety.py` | `@require_write_consent`, `describe_request`, `shown` |
| `src/nz_openbank_mcp/http_auth.py` | HTTP inbound auth: `StaticBearerAuthProvider`, `AllowlistedGoogleOAuthProvider`, encrypted `DurableOAuthStorage` |
| `src/nz_openbank_mcp/tool_metadata.py` | Tool annotations (every hint set explicitly) |
| `src/nz_openbank_mcp/formatting.py` | `format_money`, `mask_account`, `local_date`, `akahu_bound`, `nz_day`, `nz_today`, `parse_iso_date` |
| `src/nz_openbank_mcp/aio.py` | `pair`: two requests at once; a failure cancels the other and is raised as itself |

A sub-server's tools are exposed as `<namespace>_<function>`, where each
`tools/` module defines its `NAMESPACE` and `server.py` mounts it under that.
New tools go in an existing `tools/` module with `@server.tool`; a new group
is a new module plus one `mcp.mount(...)` in `server.py`.

## Rules for tools

**Docstrings feed the tool schema.** FastMCP turns the `Args:` block into
parameter descriptions and drops any `Returns:` block from the description
when `Args:` is present. Describe the output in the paragraph between the
summary line and `Args:`:

```python
"""Summary line.

Returns {"key": ...} and when to use it.

Args:
    foo: ...
"""
```

Print what hosts will see with:
`uv run python -c 'import asyncio; from nz_openbank_mcp.server import build_server; m=build_server(); [print(t.name, ":", t.description) for t in asyncio.run(m.list_tools())]'`

**Annotations come from `tool_metadata.py`** and set every hint:
`READ_ONLY_ANNOTATIONS` for reads, `REFRESH_ANNOTATIONS` for the refreshes and
`OPEN_WORLD_WRITE_ANNOTATIONS` for writes that reach a person or system beyond
the user's own Akahu data.

**Writes go through `@require_write_consent(describe, namespace=NAMESPACE, automatable=..., prepare=...)`,**
which applies, in order:

1. `AKAHU_READ_ONLY=true` (the default) raises `ReadOnlyError` before any
   request.
2. `prepare(ctx, kwargs)`, if set, validates arguments and fills missing
   values, so a doomed call fails before the user is asked and one
   confirmation covers the final request.
3. The user confirms each call. `describe` builds the prompt from the final
   arguments with `describe_request`, which lists every value sent to Akahu,
   omits empty ones, and quotes each through `shown` (control and invisible
   characters escaped; over `MAX_SHOWN_CHARS` is refused, never cut).
   On protocol 2025-11-25 and earlier this is a server-initiated
   `ctx.elicit()`. On 2026-07-28 the tool returns an `InputRequiredResult`
   with a single-use nonce in `request_state` and runs when the client
   retries with an accept and that nonce. The nonce is bound to the prompt
   text; a retry that renders different text is asked again. Mid-call value
   prompts (`elicit_value`) do not work on 2026-07-28; take values as
   arguments. Decline or cancel raises `ElicitationDeclinedError`.
4. `automatable=True` plus `AKAHU_AUTOMATION_BYPASS=true` skips step 3 and
   logs at INFO. Config validation rejects the bypass while read-only is on.

Default to `automatable=False`; only idempotent, rate-limited actions with no
third-party effect qualify. `bypass_eligible_tools()` returns their exposed
names for the startup banner, and the bypass log uses the same names.

**Data handling:**

- Account fields are shown in full unless `AKAHU_MASK_ACCOUNTS=true`; then
  they go through `mask_account`, which fails closed: formats other than NZ
  keep only their last four digits. Transaction descriptions and merchant
  names are never masked.
- `format_money` renders NZD as `$1,234.56` and other codes as
  `USD 1,234.56`; an empty code means NZD, and `None` gives `1,234.56`.
- Akahu transactions have no currency field. Tools format each one in its
  account's currency, from one `/accounts` call per invocation
  (`currency_map`). An account missing from the map gets `currency: None`,
  never a guessed NZD.
- Every emitted date goes through `local_date` (NZ calendar day). Date filter
  inputs go through `akahu_bound`, which turns a bare YYYY-MM-DD into the
  UTC instant Akahu's exclusive `start` / inclusive `end` need.
- Pending items are `PendingTransaction` (no `_id`); output them with
  `summarise_pending`.
- Tokens are `SecretStr`; call `get_secret_value()` only where headers are
  built. Never log tokens or response bodies.

## Akahu limits

- Personal App tokens get 403 from app-scoped endpoints: `/categories`,
  `/categories/{id}`, `/connections`, `/connections/{id}`, `/parties`,
  `/parties/{code}` and `/identity/{id}/verify-name`. Payments and webhooks
  are unavailable too. Do not add tools for any of them.
- Every request sends `Authorization: Bearer <user_token>` and
  `X-Akahu-Id: <app_token>`; `AkahuClient` handles both.

## Configuration

Settings come from the process environment. An env file loads only when
`AKAHU_ENV_FILE` gives an absolute path, and no settings class reads a
working-directory `.env`. `AKAHU_BASE_URL` must stay on `https://api.akahu.io`
unless `AKAHU_ALLOW_CUSTOM_BASE_URL=true` is a real environment variable; the
flag is ignored in files. `config.get_config()` reads `AkahuConfig` once per
process; the safety layer, client and banner all use it.

The HTTP entrypoint adds two settings classes, read only by `http_main`:

- `McpHttpConfig`: `NZ_OPENBANK_MCP_AUTH_MODE` (`bearer` or `oauth`),
  `NZ_OPENBANK_MCP_BEARER_TOKEN`, `NZ_OPENBANK_MCP_HTTP_HOST`, `_PORT` and
  `_PATH`, and `NZ_OPENBANK_MCP_ALLOWED_HOSTS` (Host values accepted besides
  loopback; Host and Origin are always validated, and OAuth mode adds the
  public base URL's host).
- `McpOAuthConfig` (oauth mode): `NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID` and
  `_SECRET`, `NZ_OPENBANK_MCP_PUBLIC_BASE_URL`, the sign-in allowlist
  `NZ_OPENBANK_MCP_ALLOWED_USERS` and `_ALLOWED_DOMAINS` (Google-verified
  email, hosted-domain checked), `NZ_OPENBANK_MCP_JWT_SIGNING_KEY`,
  `NZ_OPENBANK_MCP_STATE_DIR` (durable client and token storage), and
  `NZ_OPENBANK_MCP_ALLOWED_REDIRECT_URIS` (replaces the default redirect URI
  list).

`.env.example` lists every setting; `docs/public-https-streamable-http.md`
covers deployment.

## Tests

- `tests/conftest.py` env fixtures: `fake_env` (read-only), `writable_env`
  (writes elicit), `bypass_env` (automatable writes skip the prompt).
  An autouse fixture clears the `get_config()` cache around every test.
- `ctx_factory()` builds a mock `Context` whose `elicit()` returns accept,
  decline or cancel.
- `respx_mock` intercepts Akahu HTTP; `load_fixture("name")` reads
  `tests/fixtures/name.json`. Fixtures are synthetic.
- Tool tests usually patch `deps.get_client` with a `MagicMock` holding
  `AsyncMock` methods (see `_fake_client()` in `tests/test_accounts.py`).
- `tests/test_consent_e2e.py` drives consent through a real `fastmcp.Client`
  on both protocol eras.

A new tool needs the happy path and empty or missing data. A new write also
needs read-only refusal and all three consent outcomes.

## Packaging

One codebase ships as a PyPI package, a plugin for Claude Code, Codex, Cursor
and Grok Build (`plugin/`, with this repo as each host's marketplace), a
Claude Desktop Extension (`mcpb/`), and an npm launcher (`npm/`) that runs
the PyPI release of the same version through `uvx`.

All host manifests, `server.json`, `examples/claude_desktop_config.json`,
`npm/package.json` and the `npm/` copies of `LICENSE` and `NOTICE` are
generated from `plugin/plugin.base.toml` by
`scripts/sync_plugin_manifests.py`, which takes the version from
`pyproject.toml`. Edit the base file or the generator, regenerate, and commit
the output; CI fails on drift.

| Host | Manifest | Launch spec | Marketplace |
| --- | --- | --- | --- |
| Claude Code | `plugin/.claude-plugin/plugin.json` | `plugin/.mcp.json` | `.claude-plugin/marketplace.json` |
| Codex | `plugin/.codex-plugin/plugin.json` | `plugin/codex-mcp.json` | `.agents/plugins/marketplace.json` |
| Cursor | `plugin/.cursor-plugin/plugin.json` | inline `mcpServers` | `.cursor-plugin/marketplace.json` |
| Grok Build | `plugin/.grok-plugin/plugin.json` | `plugin/grok-mcp.json` | `.grok-plugin/marketplace.json` |
| Claude Desktop | `mcpb/manifest.json` | `server.mcp_config` | Release asset |

How each host gets credentials, which constrains the launch specs:

- Claude Code and the Desktop Extension prompt at install, keep values in the
  OS keychain and substitute `${user_config.KEY}`. The plugin key is
  `userConfig`; the `.mcpb` key is `user_config`.
- Codex forwards the variables listed in `env_vars` from its own environment
  and has no secret prompt.
- Cursor fills `${VAR}` from plugin `variables`, then its environment. It does
  not apply schema defaults and leaves an unset `${VAR}` literal, so the spec
  uses `${VAR:-default}`.
- Grok Build expands `${VAR:-default}` from its environment and ignores inline
  `mcpServers`, so its manifest points at a file.

Layout constraints:

- Never add `plugin/plugin.json` or `plugin/mcp.json`; Codex, Cursor and
  Grok would load them ahead of the per-host manifests.
- Never add a root `.mcp.json`; `.gitignore` blocks it with `/.mcp.json`.
- The Cursor manifest has no `displayName`, because Cursor names the server
  `plugin-<displayName or name>-akahu`.

`scripts/check_packaging.py` checks the cross-host rules: pinned launch,
placeholder-only env, pinned defaults, exact Codex variable list, every
marketplace pointing at `plugin/`, and version lockstep.

The npm launcher (`npm/lib/launch.js`, tested with `node --test
npm/test/launch.test.js`) must stay a launcher: no dependencies of any kind,
no `scripts`, no `publishConfig`, and no `.npmrc` or lock file, all enforced
by `check_packaging.py`. It installs and runs nothing else, so it needs no
minimum-release-age setting; any Node tooling added later must come with a
14-day minimum release age. `scripts/check_npm_tarball.py` checks that the
packed tarball holds exactly the files in `npm/`.

## CI and releases

`ci.yml` runs on PRs, pushes to `main`, weekly and on dispatch. PRs run only
the jobs their paths touch; other triggers run everything. The required
checks are `ci-ok` and `no personal email addresses` from `pr-hygiene.yml`.
That check keeps personal addresses off `main`: it fails a PR whose commits
are not authored and committed with a GitHub noreply address, or whose commit
messages, added lines, title or body hold a personal address
(`scripts/check_commit_emails.py`). A second job checks each push to `main`,
because the squash commit takes the merging account's commit email. Anything
pushed is public already; commit with a noreply `user.email`. Actions are pinned to commit SHAs, and Dependabot
proposes weekly grouped updates. The package build backend is pinned with hashes in
`.github/build-constraints/` (edit `requirements.in`, then recompile with the
command in `requirements.txt`); CI and the release build use it. The
`Dockerfile` installs a prebuilt wheel from `dist/` and never builds the
package itself; its header gives the local build commands.

To release: bump `version` in `pyproject.toml` and `__version__` in
`src/nz_openbank_mcp/__init__.py`, rename `## Unreleased` in `CHANGELOG.md` to
`## X.Y.Z - <date>`, regenerate the manifests, merge, tag the
merge commit `vX.Y.Z`, run `gh workflow run release.yml --ref vX.Y.Z` for the
TestPyPI dry run, then run `gh workflow run release.yml --ref vX.Y.Z -f
publish=true` and approve the `pypi` and `npm` environments (one review
dialog covers both). The workflow creates and
publishes the GitHub Release itself; never create it by hand, because releases
are immutable once published. `release.yml` builds only a tag whose commit is
on `main` with a green `ci.yml` push run. `PUBLISHING.md` has the full steps.

## Writing style

- No emojis and no em dashes in code, comments, commits or docs.
- State what was done and checked; do not claim success that was not verified.
- Comments explain why, and most code needs none.
- When asked to review, report findings before changing anything.
- Docs describe what something does and how to use it. Leave out decision
  history, audit trails and roadmaps.
