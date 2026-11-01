# nz-openbank-mcp

Unofficial MCP server for the [Akahu](https://akahu.nz) open-finance API
(New Zealand). Bring your own Akahu credentials; run locally over stdio by
default; no hosted backend.

- **14 tools.** Account & balance reads, settled & pending transaction reads, batch lookup by id, identity read, refresh writes, support-ticket writes, name verification.
- **Read-only by default.** Every write tool refuses until `AKAHU_READ_ONLY=false`.
- **Per-call consent for every write.** Each write calls `ctx.elicit()` for confirmation in the client.
- **Personal Apps only.** App-scoped endpoints, payments, and webhooks are not exposed.

## How it works

`nz-openbank-mcp` is a thin MCP adapter around Akahu Personal App endpoints:

1. You create an Akahu Personal App and provide its App Token plus your User
   Token at runtime.
2. The server sends Akahu requests with the required dual-header auth model:
   `Authorization: Bearer <user_token>` and `X-Akahu-Id: <app_token>`.
3. MCP clients call the server over one of three transports:
   - local stdio, recommended for Claude Code and Claude Desktop
   - Streamable HTTP with a static bearer token, for explicitly secured HTTP
     clients
   - Streamable HTTP with Google-backed OAuth, for public HTTPS web connectors
     such as ChatGPT custom connectors or claude.ai custom connectors
4. Read tools return masked account data. Write tools refuse by default, and
   still require per-call consent when writes are enabled.

In OAuth HTTP mode, this MCP server is both the OAuth authorization server and
the MCP resource server. Google is only the identity provider used to
verify the connecting user's Google account. Google does not receive Akahu
tokens, and connector clients should be pointed at this server's `/mcp` URL,
not at Google OAuth endpoints.

## Prerequisites

1. **Akahu Personal App + User token** - register at https://my.akahu.nz/developers
2. **[`uv`](https://docs.astral.sh/uv/)** for the `uvx` runner (or pip with a Python 3.14+ virtualenv). `uvx` downloads a matching Python automatically.
3. **[Claude Code](https://docs.claude.com/en/docs/claude-code/overview)**,
   **[Claude Desktop](https://claude.ai/download)**, or another MCP client
4. For web custom connectors: a public HTTPS hostname, a Google Cloud project,
   and a Google OAuth Web application client

The two recommended install paths below (marketplace plugin for Claude Code, `.mcpb` Desktop Extension for Claude Desktop) prompt for your tokens and store them in your OS keychain. Only the manual paths further down need shell env vars:

```bash
export AKAHU_APP_TOKEN="app_token_..."
export AKAHU_USER_TOKEN="user_token_..."
# Optional - everything below is the default:
export AKAHU_READ_ONLY=true
export AKAHU_AUTOMATION_BYPASS=false
```

## Install in Claude Code

### Marketplace plugin (recommended)

Tokens prompt at install and are stored in your OS keychain (macOS Keychain on macOS, Windows Credential Manager on Windows). No shell env or `.env` file required; the package stays unchanged on PyPI.

Claude Code v2.1.83 or later:

```text
/plugin marketplace add thatskiff33/nz-openbank-mcp
/plugin install nz-openbank-mcp@nz-openbank
```

After install, `/mcp` should show `nz-openbank-mcp` connected. See [`plugin/README.md`](plugin/README.md) for the configure / reconfigure / uninstall flow and the full table of prompted values.

> **Claude Desktop note:** the marketplace plugin path does not work in Claude Desktop today - Desktop has no UI to set marketplace-plugin `userConfig` values ([anthropics/claude-code#39827](https://github.com/anthropics/claude-code/issues/39827), [#39455](https://github.com/anthropics/claude-code/issues/39455)). Use the [Desktop Extension path](#desktop-extension-recommended) below.

### Manual install

> **Prefer the [marketplace plugin path](#marketplace-plugin-recommended) above.** The manual options below exist for users hacking on the server source, pinning a specific git ref, or running in environments without marketplace access. They all require you to manage tokens via shell env vars or `--env` flags.

#### Option A: remote install via `claude mcp add`

Once published to PyPI:

```bash
claude mcp add nz-openbank \
  --scope user \
  --env AKAHU_APP_TOKEN=app_token_... \
  --env AKAHU_USER_TOKEN=user_token_... \
  --env AKAHU_READ_ONLY=true \
  -- uvx nz-openbank-mcp
```

Before a PyPI release, install straight from GitHub:

```bash
claude mcp add nz-openbank \
  --scope user \
  --env AKAHU_APP_TOKEN=app_token_... \
  --env AKAHU_USER_TOKEN=user_token_... \
  -- uvx --from git+https://github.com/thatskiff33/nz-openbank-mcp nz-openbank-mcp
```

Scope options:
- `--scope user` - available in every Claude Code project for your user (recommended for personal banking data)
- `--scope project` - shared via `.mcp.json` checked into the repo (don't use this for tokens)
- `--scope local` - this project only, not shared (default)

#### Option B: local install via `claude mcp add` (clone + dev loop)

If you want to hack on the server:

```bash
git clone https://github.com/thatskiff33/nz-openbank-mcp.git
cd nz-openbank-mcp
uv sync --extra dev
uv run pytest         # full suite, 100% line + branch coverage

# Wire the local checkout into Claude Code:
claude mcp add nz-openbank \
  --scope user \
  --env AKAHU_APP_TOKEN=app_token_... \
  --env AKAHU_USER_TOKEN=user_token_... \
  -- uv --directory "$(pwd)" run nz-openbank-mcp
```

Restart your Claude Code session after editing source.

#### Option C: pip install from PyPI

Install into a virtualenv:

```bash
python -m venv ~/.venvs/nz-openbank-mcp
source ~/.venvs/nz-openbank-mcp/bin/activate   # Windows: ~/.venvs/nz-openbank-mcp/Scripts/activate
pip install nz-openbank-mcp
```

Then point Claude Code at the installed console script (use the absolute path):

```bash
claude mcp add nz-openbank \
  --scope user \
  --env AKAHU_APP_TOKEN=app_token_... \
  --env AKAHU_USER_TOKEN=user_token_... \
  -- ~/.venvs/nz-openbank-mcp/bin/nz-openbank-mcp
```

To upgrade later: `~/.venvs/nz-openbank-mcp/bin/pip install --upgrade nz-openbank-mcp` and restart Claude Code.

#### Verify the install

```bash
claude mcp list                # confirms 'nz-openbank' is registered
claude mcp get nz-openbank        # shows the resolved command and env
```

Inside Claude Code, ask: *"What accounts do I have?"* - it should call `nz-openbank_acct_list_accounts` and return masked account details.

## Install in Claude Desktop

### Desktop Extension (recommended)

A `.mcpb` Desktop Extension is attached to every GitHub Release. Claude Desktop auto-generates a settings UI from the bundle's `user_config` schema and persists tokens to Windows Credential Manager / macOS Keychain.

1. Download `nz-openbank-mcp-X.Y.Z.mcpb` from the [latest GitHub Release](https://github.com/thatskiff33/nz-openbank-mcp/releases/latest).
2. Double-click the file to install (or in Claude Desktop: Settings -> Extensions -> Advanced -> Install Extension).
3. Fill in the prompted values:
   - **Akahu User Token** and **Akahu App Token** (sensitive, stored in OS keychain)
   - **Read-only mode** (default `true` - leave unless you specifically need write tools)
   - **Automation bypass** (default `false` - leave unless you want to skip consent prompts for account refresh)
4. Enable the extension. Claude Desktop's MCP indicator should list `nz-openbank-mcp` as connected.

Updates: download the newer `.mcpb` from the Releases page and reinstall. The bundle launches the server with `uvx` from this GitHub repository, so code updates flow in on next launch regardless.

### Manual: `claude_desktop_config.json`

> **Prefer the [Desktop Extension path](#desktop-extension-recommended) above** - it auto-generates the settings UI, stores tokens in your OS keychain, and avoids hand-editing JSON. Use this manual path only if you can't install extensions in your environment.

Copy `examples/claude_desktop_config.json` into your Claude Desktop config and replace the placeholders. The config lives at:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Then restart Claude Desktop.

## Run standalone (no client)

```bash
# Via uvx (zero-install):
uvx nz-openbank-mcp

# Via pip (after `pip install nz-openbank-mcp` in your venv):
nz-openbank-mcp

# From a local checkout:
uv run nz-openbank-mcp
```

The server reads configuration from its process environment only. It never
loads a `.env` file from the working directory (this includes FastMCP's own
`FASTMCP_*` settings, unless `FASTMCP_ENV_FILE` is set). To use an env file (see
`.env.example`), pass its absolute path; on Linux and macOS the file must not be
writable by group or others:

```bash
AKAHU_ENV_FILE=/abs/path/to/nz-openbank.env uv run nz-openbank-mcp
```

`AKAHU_BASE_URL` must point at `https://api.akahu.io` unless
`AKAHU_ALLOW_CUSTOM_BASE_URL=true` is set in the process environment; that flag
is ignored inside an env file, and the server logs a warning at startup when a
custom host is in use. Set `AKAHU_ENV_FILE` and `AKAHU_ALLOW_CUSTOM_BASE_URL`
only in your own shell or host config, never in project files checked into a
repository you cloned.

The server speaks MCP over stdio. Inspect tool calls with:

```bash
uv run fastmcp dev src/nz_openbank_mcp/server.py
```

An authenticated Streamable HTTP entrypoint exists for explicitly secured
reverse-proxy deployments. Bearer mode is the default and keeps Claude Code,
Claude Desktop, and Claude API HTTP clients working:

```bash
export NZ_OPENBANK_MCP_AUTH_MODE=bearer
export NZ_OPENBANK_MCP_BEARER_TOKEN="$(openssl rand -base64 48)"  # 32+ characters
export NZ_OPENBANK_MCP_HTTP_HOST=127.0.0.1
export NZ_OPENBANK_MCP_HTTP_PORT=8091
export NZ_OPENBANK_MCP_HTTP_PATH=/mcp
uv run nz-openbank-mcp-http
```

OAuth mode is the recommended public connector mode for ChatGPT and Claude web
custom connectors. The MCP server is the OAuth authorization server and resource
server; Google is only the identity provider.

```bash
export NZ_OPENBANK_MCP_AUTH_MODE=oauth
export NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID="client-id.apps.googleusercontent.com"
export NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET="client-secret"
export NZ_OPENBANK_MCP_PUBLIC_BASE_URL="https://mcp.example.com/openbank-mcp"
export NZ_OPENBANK_MCP_ALLOWED_USERS="you@example.com"
# Or restrict by hosted domain:
# export NZ_OPENBANK_MCP_ALLOWED_DOMAINS="example.com"
export NZ_OPENBANK_MCP_HTTP_HOST=127.0.0.1
export NZ_OPENBANK_MCP_HTTP_PORT=8091
export NZ_OPENBANK_MCP_HTTP_PATH=/mcp
uv run nz-openbank-mcp-http
```

### Google OAuth setup for web connectors

Create the OAuth client in Google Cloud Console before starting the public
OAuth deployment:

1. Create or select a Google Cloud project.
2. Open **Google Auth Platform -> Branding** or **OAuth consent screen**.
3. Configure the app name, support email, authorized domain, and contact email.
   Add homepage, privacy policy, and terms URLs when publishing beyond a
   private test audience.
4. Open **Audience**. Use **Internal** only for a Google Workspace-only app.
   Use **External** with **Testing** and explicit test users for a private or
   pilot deployment. Move to **In production** only when the app is ready for
   broader use and any required verification is complete.
5. Open **Clients -> Create client** and choose **Web application**.
6. Add this exact Authorized redirect URI, replacing the host and path with
   your `NZ_OPENBANK_MCP_PUBLIC_BASE_URL`:

```text
https://mcp.example.com/openbank-mcp/auth/callback
```

7. Store the client ID and client secret only in the runtime environment or a
   host secret manager. Do not commit `client_secret.json`, `.env` files, or raw
   secret values.
8. Set `NZ_OPENBANK_MCP_ALLOWED_USERS` or `NZ_OPENBANK_MCP_ALLOWED_DOMAINS` so only
   expected Google accounts can receive connector tokens from this server.

The Google OAuth client must be a Web application client because this server
stores a client secret and receives authorization-code callbacks. Google
requires the redirect URI sent during login to exactly match one of the
Authorized redirect URIs configured on that client.

In ChatGPT or claude.ai web, open Settings -> Connectors -> Add custom
connector, paste `https://mcp.example.com/openbank-mcp/mcp`, then complete the
Google login and consent flow. Do not point connector clients at Google OAuth
endpoints directly.

Do not expose this banking MCP server publicly without app-level auth, HTTPS,
read-only defaults, an OAuth allowlist or bearer token, and a documented
threat-model exception.

Official Google references:

- [Using OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Manage OAuth Clients](https://support.google.com/cloud/answer/6158849)
- [Submitting your app for verification](https://support.google.com/cloud/answer/13461325)
- [Manage App Audience](https://support.google.com/cloud/answer/15549945)

## Architecture

```
+--- root FastMCP server (server.py) -----------+
| mounts 3 sub-servers, prints safety banner    |
+----+---------------+--------------+-----------+
     |               |              |
   accounts      transactions    identity
     |               |              |
     +----- AkahuClient (httpx + retry) ----+
                          |
                          v
                  https://api.akahu.io/v1
                  (dual-header auth)
```

Every write tool is decorated with `@require_write_consent` from `safety.py`.
`rg "@require_write_consent"` enumerates writes; `rg "automatable=True"`
enumerates the bypass-eligible subset.

## Read-only by default

The server starts with `AKAHU_READ_ONLY=true`. Every write tool refuses with
this message:

> Write operations are disabled. To enable: set `AKAHU_READ_ONLY=false` in the
> server's environment and restart the MCP server. Each write will require your explicit
> confirmation through Claude (or set `AKAHU_AUTOMATION_BYPASS=true` for the
> automatable subset only).

When writes ARE enabled, every write still calls `ctx.elicit()` to ask you in
Claude's UI before firing.

### Automation bypass

Setting `AKAHU_AUTOMATION_BYPASS=true` *together with* `AKAHU_READ_ONLY=false`
skips the elicit prompt for tools marked `automatable=True`:

| Tool                                    | Bypass-eligible? |
| --------------------------------------- | ---------------- |
| `accounts/refresh_all_accounts`         | YES              |
| `accounts/refresh_account`              | YES              |
| `transactions/report_transaction_issue` | NO               |
| `identity/verify_name`                  | NO               |

Each bypassed call logs at INFO with the tool name. The server prints a startup
banner listing the bypass-eligible tools.

Setting `AKAHU_AUTOMATION_BYPASS=true` with `AKAHU_READ_ONLY=true` is rejected
at startup.

## Tool reference

### Read tools (10)

**`accounts/`**
- `list_accounts` - all connected accounts (masked, formatted balances)
- `get_account(account_id)` - single account details
- `get_account_balance(account_id)` - balance only
- `get_pending_transactions(account_id)` - not-yet-settled debits/credits for one account

**`transactions/`**
- `get_transactions(account_id?, start_date?, end_date?, category?, min_amount?, max_amount?, limit=100)`
- `get_transaction(transaction_id)`
- `get_transactions_by_ids(ids)` - batch fetch by Akahu txn id (useful for webhook follow-up)
- `get_pending_transactions` - not-yet-settled across all accounts
- `search_transactions(query, limit=50)` - substring across description + merchant.name

**`identity/`**
- `get_me`

### Write tools (4)

- `accounts/refresh_all_accounts` *(bypass-eligible)*
- `accounts/refresh_account(account_id)` *(bypass-eligible)*
- `transactions/report_transaction_issue(transaction_id, issue_type, fields?, comment?, other_transaction_id?)` *(always elicits)*
- `identity/verify_name(family_name, given_name?, middle_name?, initials?, account_id?)` *(always elicits)* - requires Personal-App scope grant; without it Akahu returns 403

## Privacy & security

- Account numbers are masked by preserving the bank code, suffix, and final
  four account digits.
- Tokens and API response bodies are never logged.
- All filters are applied client-side after the API call returns. Akahu has no field-level access control for Personal Apps.
- The server runs entirely on your machine. The only outbound traffic is to `https://api.akahu.io/v1`.

## Personal Apps only

This server uses the Akahu Personal App model (per-user OAuth). The following
endpoints are not exposed because they are
[app-scoped](https://developers.akahu.nz/reference/api-akahu-io-authentication#app-scoped-endpoints)
and unreachable from a Personal App:

- `/categories` - NZFCC category taxonomy (transactions carry their category inline)
- `/connections` - supported-bank list
- `/identity/{id}/verify-name` - app-scoped variant; use `identity/verify_name` instead

Full-app features are also out of scope:

- Payments (`make_payment`, `cancel_payment`, etc.)
- Webhooks (`subscribe_webhook`, etc.)

### Scope-grant gotchas

These user-scoped endpoints require a Personal-App scope toggled at
https://my.akahu.nz/developers; without the grant they return 403:

- `GET /parties` - counterparty list (not shipped as a tool)
- `POST /verify/name` and `POST /verify/name/{id}` - shipped as `identity/verify_name`

## Releasing

To cut a release: bump `version` in `pyproject.toml`, push a `vX.Y.Z` tag, then
publish a GitHub Release with that tag. The workflow runs the test+ruff+mypy
gate, asserts the pyproject version matches the tag, and publishes to PyPI via
Trusted Publishing (OIDC).

See [`PUBLISHING.md`](PUBLISHING.md) for the one-time PyPI setup and the
manual-publish fallback.

## Disclaimer

This is an unofficial integration. Not affiliated with Akahu, your bank, or
any financial institution. Use at your own risk. The maintainers are not
responsible for any data loss, unauthorised access, or financial impact arising
from use of this software.

## License

Apache-2.0. See `LICENSE`.
