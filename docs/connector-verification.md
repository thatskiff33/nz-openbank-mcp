# Connector Verification Checklist

Use this checklist to prove the MCP server is connected, read-only by default,
and exposing the expected tools. It can be run without changing source code.
Do not paste account data, raw tool responses, screenshots, or token values into
issues, PRs, chat, or logs.

## Prerequisites

- Operator-provided Akahu tokens are present only in the runtime environment.
- `AKAHU_READ_ONLY=true`.
- `AKAHU_AUTOMATION_BYPASS=false`.
- For ChatGPT Business, `tunnel-client` has passed
  `tunnel-client doctor --profile nz-openbank --explain`.
- For the public HTTPS exception, `NZ_OPENBANK_MCP_BEARER_TOKEN` is present only in
  the runtime environment and approved MCP clients.
- For ChatGPT and Claude web public HTTPS connectors,
  `NZ_OPENBANK_MCP_AUTH_MODE=oauth`, Google OAuth credentials,
  `NZ_OPENBANK_MCP_PUBLIC_BASE_URL`, and an allowlist are present only in the
  runtime environment.
- For Claude, use Claude Code, Claude Desktop, the `.mcpb` Desktop Extension,
  or a local/manual MCP config.

ChatGPT and Claude web connectors are not part of the secure default rollout
unless the explicit public HTTPS OAuth exception is deployed. They require a
remote endpoint reachable from the vendor cloud, so keep the no-public-MCP
baseline unless OAuth mode, HTTPS, Google login, and the Google account
allowlist are all in place.

## Local Tool List

Run this from the repo checkout:

```bash
uv run python - <<'PY'
import asyncio

from nz_openbank_mcp.server import build_server

mcp = build_server()
tools = asyncio.run(mcp.list_tools())

print(len(tools))
for tool in tools:
    print(tool.name)

if len(tools) != 14:
    raise SystemExit(f"expected 14 tools, got {len(tools)}")
PY
```

Expected pass:

```text
14
acct_list_accounts
acct_get_account
acct_get_pending_transactions
acct_get_account_balance
acct_refresh_all_accounts
acct_refresh_account
txn_get_transactions
txn_get_transaction
txn_get_transactions_by_ids
txn_get_pending_transactions
txn_search_transactions
txn_report_transaction_issue
id_get_me
id_verify_name
```

Expected fail:

- Fewer or more than 14 tools.
- Missing the `acct_`, `txn_`, or `id_` namespace prefixes.
- Any unhandled Python exception.

## ChatGPT Business Connector Discovery

1. Start the tunnel and keep it running:

   ```bash
   tunnel-client run --profile nz-openbank
   ```

   For the systemd deployment:

   ```bash
   sudo systemctl start nz-openbank-tunnel.service
   sudo systemctl status nz-openbank-tunnel.service
   ```

2. Open https://chatgpt.com/#settings/Connectors.
3. Create or open the custom connector that uses Tunnel as its connection type.
4. Select the `nz-openbank` tunnel or paste the operator-provided tunnel ID.
5. Complete connector discovery.

Expected pass:

- ChatGPT shows the tunnel as available or accepts the tunnel ID.
- Connector discovery completes while `tunnel-client` is still running.
- The connector exposes the 14 tools listed in the local tool-list check.

Expected fail:

- The tunnel is not visible.
- Discovery fails while `/readyz` is not ready.
- Tool names are missing or do not match the local list.

If discovery fails, rerun:

```bash
tunnel-client doctor --profile nz-openbank --explain
```

Do not fix discovery failures by adding public Caddy, nginx, ngrok, or other
public ingress.

## Public HTTPS Connector Discovery Exception

Use this only while Secure MCP Tunnel is blocked by org/workspace association.
The connector URL is:

```text
https://mcp.example.com/openbank-mcp/mcp
```

Unauthenticated public requests must fail:

```bash
curl -i -X POST https://mcp.example.com/openbank-mcp/mcp \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Expected pass: HTTP 401.

Authenticated discovery must list 14 tools:

```bash
/opt/nz-openbank-mcp/.venv/bin/fastmcp list \
  --server-spec https://mcp.example.com/openbank-mcp/mcp \
  --transport http \
  --auth "$NZ_OPENBANK_MCP_BEARER_TOKEN" \
  --json
```

Expected pass:

- 14 tools.
- Tool names use the `acct_`, `txn_`, and `id_` prefixes.
- No token value, account data, or raw tool output is copied into public logs,
  GitHub, screenshots, or chat.

## ChatGPT and Claude Web OAuth Connector Discovery

Use this only for `NZ_OPENBANK_MCP_AUTH_MODE=oauth` public HTTPS deployments.

Verify public OAuth metadata before opening the connector UI:

```bash
curl -fsS https://mcp.example.com/.well-known/oauth-protected-resource/openbank-mcp/mcp
curl -fsS https://mcp.example.com/.well-known/oauth-authorization-server/openbank-mcp
```

Expected pass:

- The protected resource is `https://mcp.example.com/openbank-mcp/mcp`.
- The issuer is `https://mcp.example.com/openbank-mcp`.
- The authorization, token, and registration endpoints are under
  `https://mcp.example.com/openbank-mcp/`.
- No response exposes the backend listener host or port.

Configure the connector:

1. Open the ChatGPT or Claude connector settings page.
2. Select Add custom connector.
3. Paste `https://mcp.example.com/openbank-mcp/mcp`.
4. Complete Google login and consent using an allowlisted Google account.
5. Complete connector discovery.

Expected pass:

- The connector starts OAuth against this MCP server, not against Google directly.
- Google login uses
  `https://mcp.example.com/openbank-mcp/auth/callback` as the registered redirect
  URI.
- Connector discovery completes and lists the same 14 tools as the local
  tool-list check.

Expected fail:

- Metadata contains an internal host, internal port, or missing registration
  endpoint.
- Google rejects the redirect URI.
- Login succeeds for a Google account outside
  `NZ_OPENBANK_MCP_ALLOWED_USERS` or `NZ_OPENBANK_MCP_ALLOWED_DOMAINS`.
- A write tool does not refuse while `AKAHU_READ_ONLY=true`.

## Read Tool Check

Run `acct_list_accounts` from ChatGPT or from local Claude.

Expected pass:

- The tool returns connected accounts.
- Account identifiers are masked with asterisks.
- No full bank account number is visible.
- The response is not copied into an issue, PR, or chat transcript.

Expected fail:

- The tool cannot connect even though the connector is ready.
- A full unmasked account number appears.
- The response includes token values.
- Raw private financial output is captured in a ticket, PR, screenshot, or log.

Record only this kind of result:

```text
acct_list_accounts: pass - returned masked account details
```

Do not record the account rows themselves.

## Read-Only Write Refusal Check

With `AKAHU_READ_ONLY=true`, attempt one write tool such as
`acct_refresh_all_accounts`.

Expected pass:

```text
Write operations are disabled. To enable: set AKAHU_READ_ONLY=false
```

The exact response may include additional guidance about restarting the MCP
server and per-call confirmation. The important result is that the write refuses
before any Akahu write request is made.

Expected fail:

- The write succeeds.
- The client asks for write confirmation while read-only mode is still true.
- The tool call reaches Akahu instead of refusing locally.

If the write does not refuse, stop using the connector and inspect the runtime
environment before making any further calls:

```bash
env | grep -E '^(AKAHU_READ_ONLY|AKAHU_AUTOMATION_BYPASS)='
```

Expected runtime values:

```text
AKAHU_READ_ONLY=true
AKAHU_AUTOMATION_BYPASS=false
```

## Claude Code Verification

Use the marketplace plugin or a manual MCP config.

Marketplace path:

```text
/plugin marketplace add thatskiff33/nz-openbank-mcp
/plugin install nz-openbank-mcp@nz-openbank
/mcp
```

Manual local path:

```bash
claude mcp list
claude mcp get nz-openbank
```

Expected pass:

- `/mcp` or `claude mcp list` shows `nz-openbank` or `nz-openbank-mcp` connected.
- A read prompt can call `acct_list_accounts` and returns masked account
  details.
- A write prompt refuses while read-only mode is true.

Expected fail:

- The MCP server is disconnected.
- Claude cannot find `uvx`, the local checkout command, or the configured
  tokens.
- A write does not refuse while read-only mode is true.

## Claude Desktop Verification

Use the `.mcpb` Desktop Extension from the release bundle, or the manual
`claude_desktop_config.json` path documented in the README.

Expected pass:

- Claude Desktop shows the extension or MCP server as enabled and connected.
- `acct_list_accounts` returns masked account details.
- A write tool refuses while read-only mode is true.

Expected fail:

- The extension is disabled or missing required token fields.
- Desktop cannot launch `uvx` or the configured command.
- Raw account data is copied into screenshots, logs, issues, or PRs.

## Sign-Off Template

Use this template without pasting private data:

```text
tool-list: pass - 14 tools
chatgpt-discovery: pass - connector discovered tools through tunnel
public-https-401: pass|not-run - reason
public-https-auth-discovery: pass|not-run - reason
web-oauth: pass|not-run - reason
read-check: pass - acct_list_accounts returned masked account details
write-check: pass - read-only write refused locally
claude-code: pass|not-run - reason
claude-desktop: pass|not-run - reason
```
