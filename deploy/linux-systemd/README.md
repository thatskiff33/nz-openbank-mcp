# Linux Systemd Deployment Assets

These assets run `nz-openbank-mcp` on a Linux host. The secure default deployment
uses OpenAI Secure MCP Tunnel and does not publish a public MCP endpoint.
`nz-openbank-http.service` is the explicit public HTTPS Streamable HTTP exception
documented in `docs/public-https-streamable-http.md`.

## Files

- `nz-openbank-tunnel.service` - systemd unit for the long-running
  `tunnel-client run --profile nz-openbank` daemon.
- `nz-openbank-http.service` - systemd unit for the authenticated Streamable HTTP
  MCP server.
- `nz-openbank.env.example` - placeholder-only Akahu environment shared by both
  units. Copy this to `/etc/nz-openbank-mcp/nz-openbank.env` and fill values on
  the host only.
- `nz-openbank-tunnel.env.example` - placeholder-only OpenAI tunnel values,
  loaded only by `nz-openbank-tunnel.service`. Copy this to
  `/etc/nz-openbank-mcp/nz-openbank-tunnel.env`.
- `nz-openbank-http.env.example` - placeholder-only HTTP secrets, loaded only by
  `nz-openbank-http.service`. Copy this to
  `/etc/nz-openbank-mcp/nz-openbank-http.env`.
- `nz-openbank.profile.yaml` - secret-free `tunnel-client` profile for the local
  stdio MCP command.

## Install Target

Expected host paths:

```text
/usr/local/bin/tunnel-client
/opt/nz-openbank-mcp
/etc/nz-openbank-mcp/nz-openbank.env
/etc/nz-openbank-mcp/nz-openbank-tunnel.env
/etc/nz-openbank-mcp/nz-openbank-http.env
/etc/tunnel-client/profiles/nz-openbank.yaml
/etc/systemd/system/nz-openbank-tunnel.service
/etc/systemd/system/nz-openbank-http.service
```

The tunnel runs as `nz-openbank-mcp`, not as root. The HTTP service runs under
its own systemd dynamic user with state in `/var/lib/nz-openbank-http`, so the
tunnel cannot read its secrets or OAuth state. `nz-openbank.env` is root-owned
and readable only by the service group; `nz-openbank-tunnel.env` and
`nz-openbank-http.env` are root-only, and each is loaded only by its own unit,
so the HTTP process never receives the OpenAI runtime key.

## Install Commands

Run these commands from a local checkout after the operator has provided the
tunnel ID, runtime API key, and Akahu tokens out of band.

Create the service user:

```bash
getent group nz-openbank-mcp >/dev/null || sudo groupadd --system nz-openbank-mcp
id -u nz-openbank-mcp >/dev/null 2>&1 || sudo useradd --system --gid nz-openbank-mcp --home-dir /var/lib/nz-openbank-mcp \
  --shell /usr/sbin/nologin nz-openbank-mcp
sudo install -d -o nz-openbank-mcp -g nz-openbank-mcp -m 0750 /var/lib/nz-openbank-mcp
```

Install `tunnel-client` into the normal system path after downloading and
verifying the binary:

```bash
sudo install -o root -g root -m 0755 /tmp/tunnel-client /usr/local/bin/tunnel-client
/usr/local/bin/tunnel-client help quickstart
```

Install the source checkout:

```bash
REPO_URL=https://github.com/thatskiff33/nz-openbank-mcp
sudo install -d -o nz-openbank-mcp -g nz-openbank-mcp -m 0755 /opt/nz-openbank-mcp
sudo -u nz-openbank-mcp git clone "$REPO_URL" /opt/nz-openbank-mcp
sudo -u nz-openbank-mcp git -C /opt/nz-openbank-mcp checkout main
sudo -u nz-openbank-mcp uv --directory /opt/nz-openbank-mcp sync --frozen
```

Install config templates:

```bash
sudo install -d -o root -g nz-openbank-mcp -m 0750 /etc/nz-openbank-mcp
sudo install -o root -g nz-openbank-mcp -m 0640 \
  deploy/linux-systemd/nz-openbank.env.example \
  /etc/nz-openbank-mcp/nz-openbank.env
sudoedit /etc/nz-openbank-mcp/nz-openbank.env
sudo install -o root -g root -m 0600 \
  deploy/linux-systemd/nz-openbank-tunnel.env.example \
  /etc/nz-openbank-mcp/nz-openbank-tunnel.env
sudoedit /etc/nz-openbank-mcp/nz-openbank-tunnel.env

sudo install -d -o root -g root -m 0755 /etc/tunnel-client/profiles
sudo install -o root -g root -m 0644 \
  deploy/linux-systemd/nz-openbank.profile.yaml \
  /etc/tunnel-client/profiles/nz-openbank.yaml
```

Install and verify the systemd unit:

```bash
sudo install -o root -g root -m 0644 \
  deploy/linux-systemd/nz-openbank-tunnel.service \
  /etc/systemd/system/nz-openbank-tunnel.service
sudo systemd-analyze verify /etc/systemd/system/nz-openbank-tunnel.service
sudo systemctl daemon-reload
sudo systemctl enable --now nz-openbank-tunnel.service
```

## Local Verification

Confirm the daemon is running as the unprivileged user:

```bash
systemctl show nz-openbank-tunnel.service -p User -p Group -p FragmentPath
systemctl status nz-openbank-tunnel.service
```

Confirm the health/admin surface is loopback-only:

```bash
sudo ss -ltnp | grep tunnel-client
sudo cat /run/nz-openbank-mcp/tunnel-health.url
curl -fsS "$(sudo cat /run/nz-openbank-mcp/tunnel-health.url)/readyz"
```

The listen address must be `127.0.0.1`. Do not add a public reverse proxy for
the tunnel-client health/admin surface.

Confirm the read-only defaults are present:

```bash
sudo grep -E '^(AKAHU_READ_ONLY|AKAHU_AUTOMATION_BYPASS)=' /etc/nz-openbank-mcp/nz-openbank.env
```

Expected values:

```text
AKAHU_READ_ONLY=true
AKAHU_AUTOMATION_BYPASS=false
```

## Public HTTPS Exception

Use `nz-openbank-http.service` only when Secure MCP Tunnel cannot be associated
with the ChatGPT workspace. It requires:

- `NZ_OPENBANK_MCP_AUTH_MODE=oauth` with the Google OAuth vars filled. Bearer
  mode remains available only for approved clients that cannot use OAuth, and
  needs a bearer token of at least 32 characters with at least 10 distinct
  characters.
- `NZ_OPENBANK_MCP_HTTP_HOST=127.0.0.1` when Caddy runs on the same host. If the
  reverse proxy is on a separate host, bind to a private interface and firewall
  the listener so only the reverse proxy can reach it.
- `NZ_OPENBANK_MCP_HTTP_PORT=8091`.
- Caddy routing only the MCP path, the OAuth endpoints and the OAuth
  well-known routes under `https://mcp.example.com/openbank-mcp` to
  `http://127.0.0.1:8091` with the `/openbank-mcp` prefix stripped, as in
  `deploy/caddy/nz-openbank-mcp.caddy.example`.

OAuth mode requires:

- `NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID`.
- `NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET`.
- `NZ_OPENBANK_MCP_PUBLIC_BASE_URL=https://mcp.example.com/openbank-mcp`.
- `NZ_OPENBANK_MCP_ALLOWED_USERS` or `NZ_OPENBANK_MCP_ALLOWED_DOMAINS`.
- Google Cloud Console Authorized redirect URI
  `https://mcp.example.com/openbank-mcp/auth/callback`.

Install and verify:

```bash
sudo install -o root -g root -m 0600 \
  deploy/linux-systemd/nz-openbank-http.env.example \
  /etc/nz-openbank-mcp/nz-openbank-http.env
sudoedit /etc/nz-openbank-mcp/nz-openbank-http.env
sudo install -o root -g root -m 0644 \
  deploy/linux-systemd/nz-openbank-http.service \
  /etc/systemd/system/nz-openbank-http.service
sudo systemd-analyze verify /etc/systemd/system/nz-openbank-http.service
sudo systemctl daemon-reload
sudo systemctl enable --now nz-openbank-http.service
sudo ss -ltnp | grep ':8091'
```

The listener must be `127.0.0.1:8091` or a deliberately selected private
interface, not `0.0.0.0:8091`.

See `docs/public-https-streamable-http.md` for Caddy, client, and verification
commands.

## Operator-Owned Values

Only the operator may fill these values in `/etc/nz-openbank-mcp/nz-openbank.env`:

- `AKAHU_APP_TOKEN`
- `AKAHU_USER_TOKEN`

these in `/etc/nz-openbank-mcp/nz-openbank-tunnel.env`:

- `CONTROL_PLANE_TUNNEL_ID`
- `CONTROL_PLANE_API_KEY`

and these in `/etc/nz-openbank-mcp/nz-openbank-http.env`:

- `NZ_OPENBANK_MCP_BEARER_TOKEN`
- `NZ_OPENBANK_MCP_JWT_SIGNING_KEY`
- `NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID`
- `NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET`
- `NZ_OPENBANK_MCP_ALLOWED_USERS`
- `NZ_OPENBANK_MCP_ALLOWED_DOMAINS`

Do not put an OpenAI admin key in any env file or in the systemd unit. Admin
keys are for setup and tunnel-management commands only, not the long-running
daemon.
