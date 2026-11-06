# ChatGPT Business Secure MCP Tunnel Runbook

This runbook connects the local stdio `nz-openbank-mcp` server to ChatGPT Business
through OpenAI Secure MCP Tunnel. It is written for an agent that already has
operator-provided values on the host. Do not request, echo, store, or commit
real OpenAI keys, Akahu tokens, tunnel IDs, account data, or screenshots.

## Official Links

- Secure MCP Tunnel guide: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- ChatGPT connector settings: https://chatgpt.com/#settings/Connectors
- OpenAI Tunnels management: https://platform.openai.com/settings/organization/tunnels
- OpenAI Runtime API keys: https://platform.openai.com/settings/organization/api-keys

## Scope

Use Secure MCP Tunnel for this deployment because the MCP server stays private
and `tunnel-client` connects outbound to OpenAI from the host that can already
reach the local stdio server.

This path needs no public reverse proxy. If Platform-org and
ChatGPT-workspace association blocks Secure MCP Tunnel, use the public HTTPS
deployment in `docs/public-https-streamable-http.md` rather than a different
public ingress.

## Required Operator Values

The operator must provide these values out of band:

- `CONTROL_PLANE_TUNNEL_ID` from OpenAI Tunnels management.
- `CONTROL_PLANE_API_KEY`, a Runtime API key whose principal has Tunnels Read +
  Use for the target tunnel.
- `AKAHU_APP_TOKEN`.
- `AKAHU_USER_TOKEN`.

An OpenAI Admin API key is only for tunnel management tasks such as creating or
editing tunnels. Do not put an Admin API key in any env file under `/etc/nz-openbank-mcp`,
a systemd unit, shell history, or any long-running daemon environment.

## Create Or Reuse The Tunnel

1. Open https://platform.openai.com/settings/organization/tunnels.
2. Reuse an existing tunnel if it is already scoped to the ChatGPT Business
   workspace that will use this MCP server.
3. Otherwise create a new tunnel for `nz-openbank-mcp`.
4. Record the tunnel ID as `CONTROL_PLANE_TUNNEL_ID`.

If the operator uses `tunnel-client admin tunnels create|list|get`, use an
Admin API key only for that short setup command. Unset it afterwards:

```bash
unset OPENAI_ADMIN_KEY
```

## Create The Runtime Key

1. Open https://platform.openai.com/settings/organization/api-keys.
2. Create a Runtime API key for the principal that will run `tunnel-client`.
3. Grant or confirm Tunnels Read + Use for the target tunnel.
4. Store that key only as `CONTROL_PLANE_API_KEY` in the host secret env file.

The runtime key is the only OpenAI key the long-running daemon should receive.

## Prepare Environment

For a manual run, use a shell that already has operator-provided values:

```bash
export CONTROL_PLANE_TUNNEL_ID="REPLACE_WITH_OPENAI_TUNNEL_ID"
export CONTROL_PLANE_API_KEY="REPLACE_WITH_OPENAI_RUNTIME_API_KEY"
export AKAHU_APP_TOKEN="REPLACE_WITH_AKAHU_APP_TOKEN"
export AKAHU_USER_TOKEN="REPLACE_WITH_AKAHU_USER_TOKEN"
export AKAHU_READ_ONLY=true
export AKAHU_AUTOMATION_BYPASS=false
```

For the systemd deployment assets, put the Akahu values in the first file and
the two `CONTROL_PLANE_*` values in the second:

```text
/etc/nz-openbank-mcp/nz-openbank.env
/etc/nz-openbank-mcp/nz-openbank-tunnel.env
```

Keep `nz-openbank.env` root-owned and readable only by the service group, and
`nz-openbank-tunnel.env` root-only, as described in
`deploy/linux-systemd/README.md`. Only the tunnel unit loads the second file.

## Initialize The Profile

Initialize a local stdio profile with the official `sample_mcp_stdio_local`
sample. Use the installed venv console script for the MCP command:

```bash
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile nz-openbank \
  --tunnel-id "$CONTROL_PLANE_TUNNEL_ID" \
  --mcp-command "/opt/nz-openbank-mcp/.venv/bin/nz-openbank-mcp"
```

If the host uses the checked-in deployment assets, the installed
`/etc/tunnel-client/profiles/nz-openbank.yaml` profile mirrors this local stdio
configuration and loads `CONTROL_PLANE_API_KEY` from the environment.

Inspect the profile before starting the daemon:

```bash
tunnel-client profiles list
tunnel-client profiles samples show sample_mcp_stdio_local
```

## Validate With Doctor

Run doctor before creating or verifying the ChatGPT connector:

```bash
tunnel-client doctor --profile nz-openbank --explain
```

For the systemd env files, load the values into a temporary shell first:

```bash
set -a
. /etc/nz-openbank-mcp/nz-openbank.env
. /etc/nz-openbank-mcp/nz-openbank-tunnel.env
set +a
tunnel-client doctor --profile nz-openbank --profile-dir /etc/tunnel-client/profiles --explain
```

Doctor should confirm the tunnel profile can authenticate, reach OpenAI over
outbound HTTPS, and reach the configured local stdio MCP command.

## Run Tunnel-Client

Keep `tunnel-client` running while creating the ChatGPT connector and during
every ChatGPT tool call:

```bash
tunnel-client run \
  --profile nz-openbank \
  --health.listen-addr 127.0.0.1:8080 \
  --health.url-file /tmp/nz-openbank-tunnel-health.url
```

Confirm local readiness:

```bash
curl -fsS "$(cat /tmp/nz-openbank-tunnel-health.url)/readyz"
```

For systemd:

```bash
sudo systemctl start nz-openbank-tunnel.service
sudo systemctl status nz-openbank-tunnel.service
sudo cat /run/nz-openbank-mcp/tunnel-health.url
curl -fsS "$(sudo cat /run/nz-openbank-mcp/tunnel-health.url)/readyz"
```

The health/admin UI must remain loopback-only. Do not set
`ALLOW_REMOTE_UI=true` for this banking deployment.

## Create Or Verify The ChatGPT Connector

1. With `tunnel-client run` or `nz-openbank-tunnel.service` still running, open
   https://chatgpt.com/#settings/Connectors.
2. Create a custom connector for ChatGPT Business.
3. Choose Tunnel under Connection.
4. Select the available `nz-openbank-mcp` tunnel, or paste the operator-provided
   `CONTROL_PLANE_TUNNEL_ID` if ChatGPT asks for it.
5. Complete connector discovery while `tunnel-client` remains running.
6. Verify the connector lists the expected MCP tools before making any
   account-data request.

If the tunnel is not visible, confirm that the tunnel is associated with the
target workspace and that the connector operator has Tunnels Read + Use.

## Troubleshooting

- `tunnel-client doctor` fails: re-check `CONTROL_PLANE_API_KEY`, tunnel ID,
  workspace scope, outbound HTTPS to `api.openai.com:443`, and the local MCP
  command path.
- Connector discovery fails: confirm `tunnel-client run --profile nz-openbank` is
  still running, then rerun `tunnel-client doctor --profile nz-openbank --explain`.
- Tunnel is visible but cannot be edited: the operator likely has Tunnels Read
  without Tunnels Manage.
- ChatGPT tool calls fail after setup: check the local `/readyz` endpoint and
  restart `nz-openbank-tunnel.service` if the daemon is not ready.

Do not fix any of these failures by adding public ingress. This deployment
uses an outbound tunnel from the trusted host; for a public endpoint, use
`docs/public-https-streamable-http.md`.
