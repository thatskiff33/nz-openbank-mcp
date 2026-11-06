# Public HTTPS Streamable HTTP Exception

The secure default for this banking-adjacent MCP server is local stdio or
OpenAI Secure MCP Tunnel. This runbook documents the exception path for
ChatGPT or Claude web custom connectors that require a public HTTPS MCP URL.

Use the placeholder URL below throughout this document. Replace
`mcp.example.com` with a real domain you control:

```text
https://mcp.example.com/openbank-mcp/mcp
```

Do not use raw IP URLs. Remote web connectors need HTTPS with a valid domain
certificate.

## Threat Model Change

This exposes a banking MCP endpoint to the internet. The exception is
acceptable only with all of these controls in place:

- App-level auth is required by `nz-openbank-mcp-http`; unauthenticated MCP
  requests fail with HTTP 401 before tool handling.
- OAuth mode is the public connector mode for ChatGPT and Claude web.
- In OAuth mode, this server is the OAuth authorization server and resource
  server. Google is only the identity provider. Do not point connector
  clients at Google OAuth endpoints directly.
- OAuth mode requires a Google account allowlist through
  `NZ_OPENBANK_MCP_ALLOWED_USERS` or `NZ_OPENBANK_MCP_ALLOWED_DOMAINS`.
- Caddy terminates public HTTPS and proxies only the `/openbank-mcp/*` path plus
  the OAuth well-known metadata paths.
- The MCP process binds to `127.0.0.1` when Caddy runs on the same host. If
  Caddy runs on a separate host, bind to a private interface and firewall the
  listener so only the reverse proxy can reach it.
- Runtime safety remains `AKAHU_READ_ONLY=true` and
  `AKAHU_AUTOMATION_BYPASS=false`.
- The bearer token, Akahu tokens, Google OAuth secret, and any account data
  stay out of GitHub, chat, screenshots, shell history, and logs.

## Host Settings

Keep `AKAHU_READ_ONLY=true` and `AKAHU_AUTOMATION_BYPASS=false` in
`/etc/nz-openbank-mcp/nz-openbank.env`. Add these values to
`/etc/nz-openbank-mcp/nz-openbank-http.env` (root:root 0600, loaded only by
`nz-openbank-http.service`) for OAuth mode:

```bash
NZ_OPENBANK_MCP_AUTH_MODE=oauth
NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID=REPLACE_WITH_GOOGLE_CLIENT_ID
NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET=REPLACE_WITH_GOOGLE_CLIENT_SECRET
NZ_OPENBANK_MCP_PUBLIC_BASE_URL=https://mcp.example.com/openbank-mcp
NZ_OPENBANK_MCP_ALLOWED_USERS=you@example.com
# Or, for Google Workspace accounts only:
# NZ_OPENBANK_MCP_ALLOWED_DOMAINS=example.com
NZ_OPENBANK_MCP_JWT_SIGNING_KEY=REPLACE_WITH_OUTPUT_OF_openssl_rand_base64_48
NZ_OPENBANK_MCP_HTTP_HOST=127.0.0.1
NZ_OPENBANK_MCP_HTTP_PORT=8091
NZ_OPENBANK_MCP_HTTP_PATH=/mcp
```

The server checks the `Host` and `Origin` headers of every request before
authentication. It accepts loopback and, in OAuth mode, the host of
`NZ_OPENBANK_MCP_PUBLIC_BASE_URL` with its `https` origin. Caddy forwards the
original `Host`, so OAuth mode needs nothing more. In bearer mode behind a
proxy, add the public host name, or every request gets HTTP 421:

```bash
NZ_OPENBANK_MCP_ALLOWED_HOSTS=mcp.example.com
```

Ports are not checked against `Host`, so list each host name once. The
startup log lists the accepted hosts and warns when only loopback is
accepted.

OAuth mode refuses to start without these:

- `NZ_OPENBANK_MCP_JWT_SIGNING_KEY`: at least 32 bytes with at least 10
  distinct characters. Signs the tokens the
  server issues to connectors and encrypts stored client registrations. It is
  independent of the Google client secret, so rotating that secret does not
  log anyone out. Generate it with `openssl rand -base64 48`.
- `NZ_OPENBANK_MCP_STATE_DIR`: absolute directory for encrypted client
  registrations and the upstream Google tokens behind issued sessions.
  `nz-openbank-http.service` sets it to `/var/lib/nz-openbank-http` and creates
  that directory via `StateDirectory=`; the server keeps its `oauth-proxy/`
  subdirectory at mode 0700 and deletes expired entries hourly.

Upgrading from 0.1.2 or earlier: move the `NZ_OPENBANK_MCP_*` values into
`nz-openbank-http.env`, install the new unit, then delete the old OAuth state.
Connectors sign in again afterwards.

```bash
sudo rm -rf /var/lib/nz-openbank-mcp/oauth-proxy \
  /var/lib/nz-openbank-mcp/fastmcp /var/lib/nz-openbank-mcp/.local/share/fastmcp
```

Allowlist semantics:

- `NZ_OPENBANK_MCP_ALLOWED_USERS` matches the verified Google email exactly.
- `NZ_OPENBANK_MCP_ALLOWED_DOMAINS` matches only Google's hosted-domain (`hd`)
  claim, which Google sets to the primary domain of a Google Workspace account
  (secondary and alias domains do not match). A consumer Google
  account registered on an address at that domain is refused. Use
  `ALLOWED_USERS` for personal Gmail accounts.

Client redirect URIs accepted at dynamic client registration default to:

```text
https://claude.ai/api/mcp/auth_callback
https://claude.com/api/mcp/auth_callback
https://chatgpt.com/connector_platform_oauth_redirect
https://cursor.com/agents/mcp/oauth/callback
https://www.cursor.com/agents/mcp/oauth/callback
http://localhost:*
http://127.0.0.1:*
```

Override with a comma-separated `NZ_OPENBANK_MCP_ALLOWED_REDIRECT_URIS`. Entries
must be `https` with an exact path (no wildcards), or plain `http` on a loopback
host. ChatGPT uses the stable callback above because the server
advertises RFC 9207 issuer identification.

The allowlist limits which platforms can receive authorization codes, not which
accounts on them: anyone can point their own Claude or ChatGPT connector at the
server. The consent screen is the control for that, so approve only connection
requests you started yourself.
Callback references:
[Claude connector authentication](https://claude.com/docs/connectors/building/authentication),
[OpenAI connector authentication](https://developers.openai.com/plugins/build/auth).

Bearer mode remains available for approved clients that cannot use OAuth:

```bash
AKAHU_READ_ONLY=true
AKAHU_AUTOMATION_BYPASS=false
NZ_OPENBANK_MCP_AUTH_MODE=bearer
NZ_OPENBANK_MCP_BEARER_TOKEN=REPLACE_WITH_OUTPUT_OF_openssl_rand_base64_48
NZ_OPENBANK_MCP_HTTP_HOST=127.0.0.1
NZ_OPENBANK_MCP_HTTP_PORT=8091
NZ_OPENBANK_MCP_HTTP_PATH=/mcp
```

The app also accepts `OPENBANK_MCP_BEARER_TOKEN`, `OPENBANK_MCP_ALLOWED_HOSTS`, `OPENBANK_MCP_HTTP_HOST`,
`OPENBANK_MCP_HTTP_PORT`, `OPENBANK_MCP_HTTP_PATH`, and matching `OPENBANK_MCP_*` OAuth
names, but the `NZ_OPENBANK_MCP_` names are preferred. The bearer token must be
at least 32 visible ASCII characters; the server refuses to start in bearer mode otherwise.

## Google OAuth Setup

Create a Google OAuth client for this server in Google Cloud Console:

1. Create or select the Google Cloud project that will own the connector
   identity.
2. Open **Google Auth Platform -> Branding** or **OAuth consent screen**.
3. Set the app name, support email, authorized domain, and developer contact
   email. Add homepage, privacy policy, and terms URLs before publishing beyond
   a private test audience.
4. Open **Audience**. Choose **Internal** only for a Google Workspace-only app.
   Choose **External** for personal Gmail or mixed Google accounts. External
   apps start in Testing and are available only to configured test users until
   published.
5. Declare only the scopes requested by this server: `openid`, `email`, and
   `profile`. Follow the Console's verification prompts if Google classifies a
   scope or branding change as requiring verification.
6. Open **Clients -> Create client** and choose **Web application**.
7. Add this exact Authorized redirect URI:

   ```text
   https://mcp.example.com/openbank-mcp/auth/callback
   ```

8. Save the client ID and client secret into the runtime secret store or
   `/etc/nz-openbank-mcp/nz-openbank-http.env`. Do not commit `client_secret.json` or raw
   secret values.
9. Set `NZ_OPENBANK_MCP_ALLOWED_USERS` to exact Google email addresses that may
   use the connector, or set `NZ_OPENBANK_MCP_ALLOWED_DOMAINS` to Google
   Workspace domains (matched against the `hd` claim, not the email suffix).

The redirect URI must exactly match the Google OAuth client. If it differs by
scheme, host, path, or trailing path segment, Google returns
`redirect_uri_mismatch`.

Official Google references:

- https://developers.google.com/identity/protocols/oauth2/web-server
- https://support.google.com/cloud/answer/6158849
- https://support.google.com/cloud/answer/13461325
- https://support.google.com/cloud/answer/15549945

## Systemd Service

Run these privileged commands as the operator from a checked-out copy of this
repo after the selected HTTP auth mode has been configured in the env file:

```bash
sudo install -o root -g root -m 0644 \
  deploy/linux-systemd/nz-openbank-http.service \
  /etc/systemd/system/nz-openbank-http.service
sudo systemd-analyze verify /etc/systemd/system/nz-openbank-http.service
sudo systemd-analyze security nz-openbank-http.service
sudo systemctl daemon-reload
sudo systemctl enable --now nz-openbank-http.service
sudo systemctl status nz-openbank-http.service
```

Confirm it is not listening publicly:

```bash
sudo ss -ltnp | grep ':8091'
```

Expected same-host listener:

```text
127.0.0.1:8091
```

Unexpected listeners such as `0.0.0.0:8091` or `[::]:8091` are deployment
failures.

## Container

The release image runs the same HTTP server. Keep the env files from Host
Settings on the host, bind inside the container on all interfaces, publish the
port only on loopback or a private interface, and keep OAuth state on a volume:

```bash
docker run -d --name nz-openbank-http --restart unless-stopped \
  --env-file /etc/nz-openbank-mcp/nz-openbank.env \
  --env-file /etc/nz-openbank-mcp/nz-openbank-http.env \
  -e NZ_OPENBANK_MCP_HTTP_HOST=0.0.0.0 \
  -p 127.0.0.1:8091:8091 \
  -v nz-openbank-state:/var/lib/nz-openbank-mcp \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  ghcr.io/thatskiff33/nz-openbank-mcp:X.Y.Z nz-openbank-mcp-http
```

The image sets `NZ_OPENBANK_MCP_STATE_DIR=/var/lib/nz-openbank-mcp`.

## Caddy Route

Merge `deploy/caddy/nz-openbank-mcp.caddy.example` into the Caddy site that owns
your connector hostname. The important route is:

```caddy
handle /.well-known/oauth-protected-resource/openbank-mcp/mcp {
    reverse_proxy http://127.0.0.1:8091
}

handle /.well-known/oauth-authorization-server/openbank-mcp {
    reverse_proxy http://127.0.0.1:8091
}

handle_path /openbank-mcp/* {
    reverse_proxy http://127.0.0.1:8091
}
```

Use `handle_path` so public `/openbank-mcp/mcp` is proxied to backend `/mcp`.
The root well-known routes are required for OAuth protected-resource and
path-aware authorization-server discovery.

Verify and reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Verification

Unauthenticated public requests must fail:

```bash
curl -i -X POST https://mcp.example.com/openbank-mcp/mcp \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Expected result: HTTP 401.

A request whose `Host` or `Origin` is not the public host must be refused
before authentication. From the server itself:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8091/mcp \
  -H 'Host: wrong.example' -H 'Content-Type: application/json' -d '{}'
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://mcp.example.com/openbank-mcp/mcp \
  -H 'Origin: https://wrong.example' -H 'Content-Type: application/json' -d '{}'
```

Expected results: HTTP 421, then HTTP 403. A browser-based client such as the
MCP Inspector sends its own `Origin` (for example `http://localhost:6274`) and
is refused the same way; server-side connectors such as claude.ai and ChatGPT
send no `Origin` and are unaffected.

Bearer-mode authenticated discovery must show 14 tools:

```bash
OPENBANK_MCP_URL=https://mcp.example.com/openbank-mcp/mcp
/opt/nz-openbank-mcp/.venv/bin/fastmcp list \
  --server-spec "$OPENBANK_MCP_URL" \
  --transport http \
  --auth "$NZ_OPENBANK_MCP_BEARER_TOKEN" \
  --json
```

Expected result: 14 tools with the `acct_`, `txn_`, and `id_` prefixes.

OAuth metadata must advertise public URLs, not the backend host or port:

```bash
curl -fsS https://mcp.example.com/.well-known/oauth-protected-resource/openbank-mcp/mcp
curl -fsS https://mcp.example.com/.well-known/oauth-authorization-server/openbank-mcp
```

Expected values:

```text
resource: https://mcp.example.com/openbank-mcp/mcp
authorization_servers: https://mcp.example.com/openbank-mcp
issuer: https://mcp.example.com/openbank-mcp
authorization_endpoint: https://mcp.example.com/openbank-mcp/authorize
token_endpoint: https://mcp.example.com/openbank-mcp/token
registration_endpoint: https://mcp.example.com/openbank-mcp/register
```

Bearer-mode read-only write refusal must still happen locally before Akahu is
called:

```bash
/opt/nz-openbank-mcp/.venv/bin/fastmcp call \
  --server-spec "$OPENBANK_MCP_URL" \
  --transport http \
  --auth "$NZ_OPENBANK_MCP_BEARER_TOKEN" \
  --target acct_refresh_all_accounts \
  --json
```

Expected result: a refusal containing `Write operations are disabled`.

## Client Examples

ChatGPT or Claude web custom connector:

1. Open Settings -> Connectors.
2. Select Add custom connector.
3. Paste this connector URL:

   ```text
   https://mcp.example.com/openbank-mcp/mcp
   ```

4. Complete Google login and consent.
5. Confirm the connector lists the 14 `acct_`, `txn_`, and `id_` tools before
   running any read checks.

Claude Code:

```bash
claude mcp add --transport http nz-openbank \
  https://mcp.example.com/openbank-mcp/mcp \
  --header "Authorization: Bearer <token>"
```

Claude API:

```json
{
  "mcp_servers": [
    {
      "type": "url",
      "name": "nz-openbank",
      "url": "https://mcp.example.com/openbank-mcp/mcp",
      "authorization_token": "<token>"
    }
  ]
}
```

Bearer-header clients such as Claude Code and the Claude API may still use
bearer mode when explicitly configured with `NZ_OPENBANK_MCP_AUTH_MODE=bearer`.
