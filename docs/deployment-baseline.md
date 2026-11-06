# Deployment Baseline

This runbook defines the source, safety posture, and validation gate for a
hardened Akahu MCP deployment. It is repo guidance only. Agents may open PRs
that update docs, templates, and validation code, but they must not invent,
echo, or commit operator-owned secrets.

## Source Of Truth

Use a reviewed source tree that contains the security hardening and OAuth
HTTP-mode changes before deploying this server for real banking data.

Deploy from a tagged release or a reviewed commit of this repository. Verify
that the release contains the commits you intend to run and that a local smoke
test passes before changing a live deployment source.

Useful evidence commands:

```bash
git fetch origin --tags --prune
gh release view --repo thatskiff33/nz-openbank-mcp --json tagName,publishedAt,targetCommitish,url
git branch --contains <required-commit>
```

## Safety Posture

Production defaults must preserve read-only behavior:

```bash
AKAHU_READ_ONLY=true
AKAHU_AUTOMATION_BYPASS=false
```

With this posture, read tools may return account and transaction data,
but write tools refuse before calling Akahu. Do not set
`AKAHU_READ_ONLY=false` for routine ChatGPT or Claude use. Do not set
`AKAHU_AUTOMATION_BYPASS=true` unless an operator has explicitly approved an
unattended automation use case and read-only mode has already been disabled.

Run the HTTP server as a single process. On 2026-07-28 MCP connections, write
consent spans two requests and its state is held in process memory, so a
retry that lands on another worker is refused.

The default deployment must not expose this banking MCP surface through public
Caddy, nginx, ngrok, or another internet-reachable reverse proxy. A public
endpoint turns a local personal-banking tool into a remote attack surface.

There is one documented exception: `docs/public-https-streamable-http.md`.
Use it only when a remote web connector cannot use local stdio or OpenAI Secure
MCP Tunnel. The exception requires OAuth mode for ChatGPT and Claude web
connectors, public HTTPS, a backend listener bound only to loopback or a
private interface, and the same read-only defaults above. Bearer mode remains
available for approved clients that cannot use OAuth.

## Client Paths

Use these paths in order of preference:

1. Local stdio for Claude Code, Claude Desktop, and local MCP hosts.
2. OpenAI Secure MCP Tunnel for ChatGPT Business when the workspace and
   Platform org can be associated.
3. Public HTTPS OAuth mode only when the client must reach the MCP server from
   the vendor cloud and tunnel access is unavailable.

Example public HTTPS OAuth connector URL:

```text
https://mcp.example.com/openbank-mcp/mcp
```

## Operator Gates

Agents may prepare PR-able repository work:

- docs and runbooks
- placeholder-only deployment templates
- validation commands
- tests and source changes that do not include private data

Operators must provide these values out of band and only at the point of live
configuration:

- Akahu app token
- Akahu user token
- OpenAI tunnel ID
- OpenAI runtime API key
- HTTP MCP bearer token for approved legacy bearer-mode clients
- Google OAuth client ID and client secret for public web connector OAuth mode
- Google account allowlist values for public web connector OAuth mode

Agents must not invent these values, request that they be pasted into GitHub, or
commit them to the repository. OpenAI admin keys are for operator setup tasks
only and must not be stored in a long-running service environment.

## Validation Gate

Run the standard local gate before merging deployment-related changes:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
uv run bandit -r src
uv export --frozen --no-emit-project --all-extras --format requirements-txt \
  | uv run pip-audit --strict --disable-pip --require-hashes -r /dev/stdin
```

`uv run pytest` enforces 100% line and branch coverage for the Python package.
Documentation-only changes should still run the same gate before merge so the
deployment branch proves it is based on a healthy source tree.

For the bearer-mode public HTTPS exception, also verify:

```bash
curl -i -X POST https://mcp.example.com/openbank-mcp/mcp \
  -H 'Content-Type: application/json' \
  -d '{}'
/opt/nz-openbank-mcp/.venv/bin/fastmcp list \
  --server-spec https://mcp.example.com/openbank-mcp/mcp \
  --transport http \
  --auth "$NZ_OPENBANK_MCP_BEARER_TOKEN" \
  --json
```

The first command must return HTTP 401. The second must list 14 tools. For
OAuth mode, verify the well-known metadata and connector flow in
`docs/public-https-streamable-http.md` and `docs/connector-verification.md`.

## Production Change Rule

A repository PR may update this baseline, add deployment templates, or document
new verification steps. It must not change live source, install secrets, or
enable writes unless the operator explicitly performs those actions on the
host.
