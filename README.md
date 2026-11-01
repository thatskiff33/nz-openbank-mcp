# nz-openbank-mcp

Ask an AI assistant about your New Zealand bank accounts without handing your
banking credentials to anyone new. `nz-openbank-mcp` is a Model Context
Protocol server that talks to [Akahu](https://akahu.nz), the NZ open-finance
service, using a Personal App you create and control. It runs on your own
machine, starts read-only, and asks before anything changes.

[PyPI](https://pypi.org/project/nz-openbank-mcp/) ·
[Releases](https://github.com/thatskiff33/nz-openbank-mcp/releases) ·
[Security policy](SECURITY.md)

> Unofficial. Not affiliated with or endorsed by Akahu or any bank.

## What it can do

The server exposes 14 tools. Ten only read; four change something and are
off until you turn writes on.

| Tool | Writes? | Purpose |
| --- | --- | --- |
| `acct_list_accounts` | | Every connected account, with masked numbers and balances |
| `acct_get_account` | | One account by id |
| `acct_get_account_balance` | | Just the balance of one account |
| `acct_get_pending_transactions` | | Unsettled transactions for one account |
| `txn_get_transactions` | | Settled transactions, filtered by account, dates, category or amount (default 100) |
| `txn_get_transaction` | | One transaction by id |
| `txn_get_transactions_by_ids` | | Several transactions in one request |
| `txn_get_pending_transactions` | | Unsettled transactions across all accounts |
| `txn_search_transactions` | | Case-insensitive text search over description and merchant (default 50) |
| `id_get_me` | | The Akahu user's profile |
| `acct_refresh_all_accounts` | yes | Ask Akahu to fetch fresh data for every account |
| `acct_refresh_account` | yes | Ask Akahu to fetch fresh data for one account |
| `txn_report_transaction_issue` | yes | Open a support ticket with Akahu about a transaction |
| `id_verify_name` | yes | Check a name against the account holder (needs an extra scope, see [Limits](#limits)) |

There are no spending reports, budgets or forecasts built in. The assistant
works those out from the transactions, which keeps the server small and easy
to audit.

## Get your Akahu tokens

1. Sign in at [my.akahu.nz/developers](https://my.akahu.nz/developers) and
   create a Personal App.
2. Connect the bank accounts you want the assistant to see.
3. Copy the **App Token** (`app_token_...`) and **User Token**
   (`user_token_...`).

Treat both like passwords. The install steps below keep them out of project
files.

You also need [`uv`](https://docs.astral.sh/uv/). Every install path runs the
server with `uvx`, which fetches the pinned release and a matching Python.

## Install

| Where you use it | How | Where the tokens live |
| --- | --- | --- |
| Claude Code | Plugin from this repo's marketplace | OS keychain, prompted at install |
| Claude Desktop | `.mcpb` Desktop Extension | OS keychain, prompted at install |
| Codex | Plugin from this repo's marketplace | Environment Codex starts in |
| Cursor | Plugin from this repo's marketplace | Cursor plugin settings |
| Grok Build | Plugin from this repo's marketplace | Environment Grok starts in |
| claude.ai, ChatGPT, grok.com | Self-hosted HTTPS server with OAuth | Your server's environment |
| Anything else that speaks MCP | `uvx nz-openbank-mcp` | Environment of the client |

Every option below starts with `AKAHU_READ_ONLY=true` and
`AKAHU_AUTOMATION_BYPASS=false`.

### Claude Code

```text
/plugin marketplace add thatskiff33/nz-openbank-mcp
/plugin install nz-openbank-mcp@nz-openbank
```

Claude Code asks for both tokens and the two safety settings. `/mcp` should
then list the server as connected. To change a setting later, open `/plugin`,
pick the plugin and choose **Configure options**. More detail, including
updates and removal, is in [`plugin/README.md`](plugin/README.md).

### Claude Desktop

Download `nz-openbank-mcp-X.Y.Z.mcpb` from the
[latest release](https://github.com/thatskiff33/nz-openbank-mcp/releases/latest)
and open it, or use **Settings -> Extensions -> Advanced -> Install
Extension**. Desktop shows a form for the tokens and settings. To update,
install the newer `.mcpb`.

The Claude Code plugin does not work in Claude Desktop, because Desktop cannot
collect plugin settings yet.

### Codex, Grok Build

Neither host can prompt for a plugin secret, so the tokens come from the
environment you start the host in. Read them from your OS secret store rather
than writing them into a dotfile:

```bash
# macOS
export AKAHU_USER_TOKEN="$(security find-generic-password -s akahu-user-token -w)"
export AKAHU_APP_TOKEN="$(security find-generic-password -s akahu-app-token -w)"
# Linux (libsecret)
export AKAHU_USER_TOKEN="$(secret-tool lookup service akahu-user-token)"
export AKAHU_APP_TOKEN="$(secret-tool lookup service akahu-app-token)"
```

An `AKAHU_READ_ONLY` or `AKAHU_AUTOMATION_BYPASS` already exported in that
shell overrides the safe defaults.

Codex:

```bash
codex plugin marketplace add thatskiff33/nz-openbank-mcp
codex plugin add nz-openbank-mcp@nz-openbank
codex mcp list          # shows the akahu server
```

Codex passes only the four `AKAHU_*` settings through to the server. Update
with `codex plugin marketplace upgrade nz-openbank`.

Grok Build:

```bash
grok plugin marketplace add thatskiff33/nz-openbank-mcp
grok plugin install nz-openbank-mcp --trust
grok mcp doctor akahu   # should report 14 tools
```

Grok also loads Claude Code plugins. Install in one of the two, not both, or
you get two copies of the server.

### Cursor

```bash
agent plugin marketplace add https://github.com/thatskiff33/nz-openbank-mcp
```

Install **nz-openbank-mcp** from **Customize** (or `/plugins` in the Cursor
CLI), then enter the two tokens under **Plugins -> Configure**. Cursor stores
them, not the repo. Leave the safety settings empty to keep the defaults. The
server shows up as `plugin-nz-openbank-mcp-akahu`. To try a local checkout, start the
Cursor CLI with `--plugin-dir /path/to/nz-openbank-mcp/plugin`; it then reads
unset settings from its own environment.

### Web connectors (claude.ai, ChatGPT, grok.com)

Web assistants can only reach servers on the public internet. Run the HTTP
entrypoint behind HTTPS with OAuth: this server acts as the OAuth
authorization server, Google confirms who is signing in, and only the Google
accounts or Workspace domains you allow get through. Google never sees your
Akahu tokens.

Setup, the Google client, the redirect allowlist and hardening are covered in
[docs/public-https-streamable-http.md](docs/public-https-streamable-http.md),
with a systemd example under [`deploy/linux-systemd/`](deploy/linux-systemd/).
grok.com's connector callback,
`https://grok.com/connectors-oauth-exchange-code/`, is not in the default
redirect list. `NZ_OPENBANK_MCP_ALLOWED_REDIRECT_URIS` replaces that list, so
include any default entries you still need alongside it.

### Any other MCP client

Point the client at this command and give it the settings as environment
variables:

```bash
uvx --from nz-openbank-mcp==0.1.1 nz-openbank-mcp
```

[`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)
shows the shape most JSON-configured clients expect.

## Settings

The server reads its settings from environment variables only. It does not
pick up a `.env` file from the working directory.

| Variable | Default | Meaning |
| --- | --- | --- |
| `AKAHU_USER_TOKEN` | (required) | Your User Token |
| `AKAHU_APP_TOKEN` | (required) | Your Personal App's App Token |
| `AKAHU_READ_ONLY` | `true` | Refuse every write tool |
| `AKAHU_AUTOMATION_BYPASS` | `false` | Skip the confirmation prompt for the two refresh tools |
| `AKAHU_REQUEST_TIMEOUT` | `10` | Seconds per Akahu request (1 to 120) |
| `AKAHU_LOG_LEVEL` | `INFO` | Standard Python log level |
| `AKAHU_ENV_FILE` | (unset) | Absolute path to an env file to load; on Linux and macOS it must be yours (or root's) and not writable by group or others |
| `AKAHU_BASE_URL` | `https://api.akahu.io/v1` | Must stay on `api.akahu.io` unless the next setting is on |
| `AKAHU_ALLOW_CUSTOM_BASE_URL` | `false` | Allow another API host; honoured only from the process environment, never from an env file |

The HTTP entrypoint has its own `NZ_OPENBANK_MCP_*` settings, listed in
[`.env.example`](.env.example) and the HTTPS guide.

## How writes are guarded

Three checks sit in front of every write tool:

1. **Read-only switch.** With `AKAHU_READ_ONLY=true` the tool refuses before
   any request leaves your machine.
2. **Confirmation.** With writes on, the server asks you to approve each call
   through your assistant's confirmation prompt. Declining or dismissing it
   cancels the call.
3. **Narrow bypass.** `AKAHU_AUTOMATION_BYPASS=true` skips the prompt only for
   `acct_refresh_all_accounts` and `acct_refresh_account`, which just ask Akahu
   to re-sync. Each skipped prompt is logged, the startup banner lists these
   tools, and the server will not start with the bypass on while read-only is
   also on. Support tickets and name checks always ask.

## Limits

Akahu Personal Apps cannot reach app-scoped endpoints, so this server has no
tools for categories (transactions carry theirs inline), the list of supported
banks, payments or webhooks.

`id_verify_name` and the parties endpoint need a scope you enable for your
Personal App at [my.akahu.nz/developers](https://my.akahu.nz/developers);
without it Akahu answers 403.

Transactions carry no currency of their own and are shown in NZD. For a
foreign-currency account, read the account's currency with
`acct_get_account`.

## Privacy

- Account numbers are masked to the bank code, the last four account digits
  and the suffix.
- Tokens are never logged. Balances and transaction contents are not logged; request paths, which can
  include Akahu account or transaction ids, are logged with their status.
- Over stdio, the server's only network traffic is to `api.akahu.io` (plus
  `uvx` downloading the package). HTTP mode adds Google for sign-in.
- Filters such as date, amount and category are applied after Akahu returns
  the data; Personal Apps have no finer-grained access control.

Report vulnerabilities privately through [`SECURITY.md`](SECURITY.md).

## Development

```bash
git clone https://github.com/thatskiff33/nz-openbank-mcp.git
cd nz-openbank-mcp
uv sync --extra dev
uv run pytest                 # 100% line and branch coverage is required
uv run ruff check . && uv run mypy src
FASTMCP_ENV_FILE=/dev/null uv run fastmcp dev src/nz_openbank_mcp/server.py
```

To use a local checkout from Claude Code:

```bash
claude mcp add nz-openbank --scope user \
  --env AKAHU_APP_TOKEN=app_token_... --env AKAHU_USER_TOKEN=user_token_... \
  -- uv --directory "$(pwd)" run nz-openbank-mcp
```

The host plugin manifests are generated. Edit `plugin/plugin.base.toml`, then
run `uv run --no-project python scripts/sync_plugin_manifests.py`. Releases
are described in [`PUBLISHING.md`](PUBLISHING.md); further operator guides are
in [`docs/`](docs/).

## License and disclaimer

Licensed under Apache-2.0; see [`LICENSE`](LICENSE).

This software is provided as is. You are responsible for how you use it with
your financial data. The maintainers accept no liability for data loss,
unauthorised access or financial loss arising from its use.
