# Secrets, Rotation, And Incident Runbook

This runbook covers operator-managed deployment secrets for `nz-openbank-mcp`. It
preserves the read-only default and avoids public MCP exposure.

## References

- Akahu Personal Apps: https://developers.akahu.nz/me/docs/personal-apps
- Akahu Personal Apps advanced security: https://developers.akahu.nz/me/docs/personal-apps-advanced
- Akahu revoke token endpoint: https://developers.akahu.nz/reference/delete_token
- OpenAI Runtime API keys: https://platform.openai.com/settings/organization/api-keys
- OpenAI Tunnels management: https://platform.openai.com/settings/organization/tunnels

## Secret Locations

The live secret file is:

```text
/etc/nz-openbank-mcp/nz-openbank.env
```

It contains only runtime values:

- `CONTROL_PLANE_TUNNEL_ID`
- `CONTROL_PLANE_API_KEY`
- `AKAHU_APP_TOKEN`
- `AKAHU_USER_TOKEN`
- for the HTTP service: `NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET`,
  `NZ_OPENBANK_MCP_JWT_SIGNING_KEY` or `NZ_OPENBANK_MCP_BEARER_TOKEN`
- safety and logging settings

The systemd unit is:

```text
/etc/systemd/system/nz-openbank-tunnel.service
```

The unit must reference the env file. It must not contain token values.

The server does not read this file by itself. systemd loads it through
`EnvironmentFile=`; for manual runs, either source it into the shell or set
`AKAHU_ENV_FILE=/etc/nz-openbank-mcp/nz-openbank.env`. It never reads a `.env`
from the working directory.

## Permissions

Set root ownership and service-group read access:

```bash
sudo install -d -o root -g nz-openbank-mcp -m 0750 /etc/nz-openbank-mcp
sudo chown root:nz-openbank-mcp /etc/nz-openbank-mcp/nz-openbank.env
sudo chmod 0640 /etc/nz-openbank-mcp/nz-openbank.env
```

Verify permissions without printing secret values:

```bash
sudo stat -c '%U:%G %a %n' /etc/nz-openbank-mcp /etc/nz-openbank-mcp/nz-openbank.env
sudo namei -l /etc/nz-openbank-mcp/nz-openbank.env
```

Expected pass:

```text
root:nz-openbank-mcp 750 /etc/nz-openbank-mcp
root:nz-openbank-mcp 640 /etc/nz-openbank-mcp/nz-openbank.env
```

Verify the read-only safety defaults:

```bash
sudo grep -E '^(AKAHU_READ_ONLY|AKAHU_AUTOMATION_BYPASS)=' /etc/nz-openbank-mcp/nz-openbank.env
```

Expected pass:

```text
AKAHU_READ_ONLY=true
AKAHU_AUTOMATION_BYPASS=false
```

## Stop And Restart The Service

Temporarily stop the tunnel before rotating a secret:

```bash
sudo systemctl stop nz-openbank-tunnel.service
systemctl is-active nz-openbank-tunnel.service || true
```

Expected stopped state:

```text
inactive
```

Restart after updating the env file:

```bash
sudo systemctl restart nz-openbank-tunnel.service
sudo systemctl status nz-openbank-tunnel.service --no-pager
```

Confirm readiness:

```bash
sudo cat /run/nz-openbank-mcp/tunnel-health.url
curl -fsS "$(sudo cat /run/nz-openbank-mcp/tunnel-health.url)/readyz"
```

## Rotate Akahu User Access Token

Use this when `AKAHU_USER_TOKEN` is exposed, suspected stale, or intentionally
rotated.

1. Stop the service.
2. Sign in to https://my.akahu.nz/developers.
3. In the Personal App settings, use the Danger Zone option to regenerate the
   User Access Token.
4. Open the host env file with `sudoedit`:

   ```bash
   sudoedit /etc/nz-openbank-mcp/nz-openbank.env
   ```

5. Replace only `AKAHU_USER_TOKEN`.
6. Confirm the safety defaults are still set to read-only:

   ```bash
   sudo grep -E '^(AKAHU_READ_ONLY|AKAHU_AUTOMATION_BYPASS)=' /etc/nz-openbank-mcp/nz-openbank.env
   ```

7. Restart the service.
8. Run:

   ```bash
   set -a
   . /etc/nz-openbank-mcp/nz-openbank.env
   set +a
   tunnel-client doctor --profile nz-openbank --profile-dir /etc/tunnel-client/profiles --explain
   ```

Akahu states regenerated User Access Tokens take effect immediately. Old token
use should return `401 Unauthorized`.

## Rotate Akahu App Token

Use this when `AKAHU_APP_TOKEN` is exposed or the Personal App itself may be
compromised.

1. Stop the service.
2. Sign in to https://my.akahu.nz/developers.
3. If the Developers page offers an App ID Token regeneration action, use it
   and update `AKAHU_APP_TOKEN` in `/etc/nz-openbank-mcp/nz-openbank.env`.
4. If no App ID Token regeneration action is available, delete the Personal App
   from the Danger Zone and create a new Personal App. This revokes the old app
   credentials.
5. Update both `AKAHU_APP_TOKEN` and `AKAHU_USER_TOKEN` if the new app flow
   shows both values.
6. Preserve:

   ```text
   AKAHU_READ_ONLY=true
   AKAHU_AUTOMATION_BYPASS=false
   ```

7. Restart and verify readiness.

Deleting a Personal App revokes its credentials immediately. Treat this as a
breaking change until the new values are installed and the connector is
verified.

## Rotate OAuth JWT Signing Key

Use this when `NZ_OPENBANK_MCP_JWT_SIGNING_KEY` is exposed or intentionally
rotated. Rotation signs every connector out and makes stored client
registrations undecryptable, so connectors re-register and users sign in again.

1. Generate a new key:

   ```bash
   openssl rand -base64 48
   ```

2. Stop `nz-openbank-http.service`.
3. Replace only `NZ_OPENBANK_MCP_JWT_SIGNING_KEY` with `sudoedit
   /etc/nz-openbank-mcp/nz-openbank.env`.
4. Optionally remove the old encrypted registrations:

   ```bash
   sudo rm -rf /var/lib/nz-openbank-mcp/oauth-proxy
   ```

5. Start the service and reconnect each connector.

## Rotate Google OAuth Client Secret

The signing key is independent of the Google client secret, so rotating the
secret does not sign connectors out.

1. In Google Cloud Console, open the OAuth client and add a new secret.
2. Replace `NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET` with `sudoedit`.
3. Restart `nz-openbank-http.service` and confirm a connector still works.
4. Disable and delete the old secret in Google Cloud Console.

## Rotate OpenAI Runtime API Key

Use this when `CONTROL_PLANE_API_KEY` is exposed, intentionally rotated, or the
runtime principal changes.

1. Open https://platform.openai.com/settings/organization/api-keys.
2. Create a new Runtime API key for the tunnel daemon principal.
3. Confirm the principal has Tunnels Read + Use for the target tunnel.
4. Stop the service.
5. Edit the env file:

   ```bash
   sudoedit /etc/nz-openbank-mcp/nz-openbank.env
   ```

6. Replace only `CONTROL_PLANE_API_KEY`.
7. Restart the service.
8. Run:

   ```bash
   set -a
   . /etc/nz-openbank-mcp/nz-openbank.env
   set +a
   tunnel-client doctor --profile nz-openbank --profile-dir /etc/tunnel-client/profiles --explain
   ```

9. Revoke the old Runtime API key in the OpenAI dashboard after the new key is
   verified.

If the old runtime key is known to be exposed, revoke it first and accept the
temporary outage.

## Admin API Key Rule

OpenAI Admin API keys are for short-lived tunnel management commands only. They
must not be stored in systemd or in `/etc/nz-openbank-mcp/nz-openbank.env`.

Safe check for accidental admin-key variable names:

```bash
sudo grep -RIn 'OPENAI_ADMIN_KEY' /etc/systemd/system/nz-openbank-tunnel.service /etc/nz-openbank-mcp || true
```

Expected pass: no output.

If an Admin API key was pasted into the host, revoke it from the OpenAI dashboard
and remove it from shell history or logs as described below.

## If A Token Is Pasted Into Shell History Or Logs

Do not rely on deleting history as the only fix. Rotate or revoke the exposed
secret first.

Stop the service if the exposed value is currently active:

```bash
sudo systemctl stop nz-openbank-tunnel.service
```

Inspect shell history with variable values redacted:

```bash
history | sed -E 's/((AKAHU_(APP|USER)_TOKEN|CONTROL_PLANE_API_KEY|OPENAI_ADMIN_KEY)=)[^[:space:]]+/\1REDACTED/g' \
  | grep -E 'AKAHU_(APP|USER)_TOKEN|CONTROL_PLANE_API_KEY|OPENAI_ADMIN_KEY' || true
```

Delete matching shell history entries by number, newest first, then write the
updated history file:

```bash
history -d LINE_NUMBER
history -w
```

Inspect recent service logs with variable assignments redacted:

```bash
sudo journalctl -u nz-openbank-tunnel.service --since today --no-pager \
  | sed -E 's/((AKAHU_(APP|USER)_TOKEN|CONTROL_PLANE_API_KEY|OPENAI_ADMIN_KEY)=)[^[:space:]]+/\1REDACTED/g' \
  | grep -E 'AKAHU_(APP|USER)_TOKEN|CONTROL_PLANE_API_KEY|OPENAI_ADMIN_KEY' || true
```

Expected pass: no output.

If logs contain secret material, rotate or revoke the affected secret. Do not
paste the log line into an issue or PR.

## Confirm No Public MCP Endpoint Exists

The expected deployment has only outbound tunnel traffic plus loopback health
and admin surfaces.

List listening sockets:

```bash
sudo ss -ltnp
```

Check tunnel-client listeners:

```bash
sudo ss -ltnp | grep tunnel-client || true
```

Expected pass: any `tunnel-client` listener is bound to `127.0.0.1` or `::1`.

Check common public reverse-proxy configs for accidental MCP routing:

```bash
sudo grep -RInE 'nz-openbank|tunnel-client|mcp|127\.0\.0\.1:8080|8080' /etc/caddy /etc/nginx 2>/dev/null || true
docker ps --format '{{.Names}} {{.Ports}}' | grep -Ei 'akahu|mcp|8080' || true
```

Expected pass: no unplanned Caddy, nginx, Docker, or ngrok-style route
forwards public traffic to this MCP service. The only planned public route is
the authenticated exception in `docs/public-https-streamable-http.md`.

## Do Not Do This

- Do not expose `nz-openbank-mcp` through public Caddy or nginx routing except
  for the authenticated public HTTPS exception documented in
  `docs/public-https-streamable-http.md`.
- Do not use ngrok or another public tunnel for this banking MCP surface.
- Do not put OpenAI Admin API keys in systemd, env files, wrapper scripts, or
  shell profiles.
- Do not set `AKAHU_READ_ONLY=false` as part of secret rotation.
- Do not paste token values into GitHub issues, PRs, ChatGPT, Claude, or logs.
- Do not fix a connector problem by publishing an ad hoc public MCP endpoint.
