# Threat Model

This document describes what `nz-openbank-mcp` protects, where its trust
boundaries sit, and which controls the code and deployment templates provide.
Report suspected vulnerabilities through
[SECURITY.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/SECURITY.md).

## Scope and assets

| Asset | Where it lives |
| --- | --- |
| Akahu app token and user token | Process environment, from the MCP host's keychain-backed settings or a host env file |
| Account and transaction data | Fetched from Akahu per call, returned to the MCP client; not persisted by the server |
| Inbound bearer token (HTTP bearer mode) | `NZ_OPENBANK_MCP_BEARER_TOKEN` in the HTTP env file |
| Google OAuth client secret (HTTP OAuth mode) | `NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET` in the HTTP env file |
| JWT signing key (HTTP OAuth mode) | `NZ_OPENBANK_MCP_JWT_SIGNING_KEY` in the HTTP env file |
| OAuth state directory | `$NZ_OPENBANK_MCP_STATE_DIR/oauth-proxy/`: client registrations, authorization codes, token mappings, upstream Google access and refresh tokens |

The Akahu user token grants read access to every account the user connected
to their Personal App, plus the refresh, support-ticket and name-check
endpoints. Whoever holds both Akahu tokens can do anything this server can do.

## Trust boundaries

- **MCP client and LLM.** Not trusted. The model chooses every tool argument.
  Akahu data returned to the model (transaction descriptions, merchant names)
  is third-party text and may contain injected instructions.
- **Local server process.** Trusted. Holds the tokens in memory as
  `SecretStr` values and enforces the write-safety layers.
- **Akahu API.** Trusted upstream. Receives both tokens on every request at
  `https://api.akahu.io/v1` unless a custom host is opted in.
- **Google.** Trusted identity provider in HTTP OAuth mode only. Supplies the
  verified email and hosted-domain (`hd`) claims that the allowlist checks.
- **Reverse proxy.** Trusted in HTTP mode. Terminates TLS, sees plaintext MCP
  traffic and bearer tokens, and should forward only the MCP and OAuth
  well-known paths.
- **Host.** Fully trusted. Anyone controlling the process environment, env
  files, state directory or memory controls the server.

## Deployment modes

**Local stdio (default).** `nz-openbank-mcp` runs as a child process of the MCP
host and has no network listener. The Claude Code plugin and Claude Desktop
Extension inject tokens from OS keychain-backed settings and launch the PyPI
release pinned to an exact version (`nz-openbank-mcp==X.Y.Z`). The OpenAI
Secure MCP Tunnel template runs the same stdio command under `tunnel-client`
with outbound-only traffic and a loopback health listener. The container image
runs the same command as a non-root user.

**Self-hosted Streamable HTTP.** `nz-openbank-mcp-http` serves MCP over HTTP
and requires inbound authentication in one of two modes:

- `bearer`: one static token, compared in constant time.
- `oauth`: the server is the OAuth authorization and resource server, with
  Google as the identity provider and an email or domain allowlist.

The process binds to `127.0.0.1:8091` by default and speaks plain HTTP. TLS
comes from a reverse proxy in front of a public URL such as
`https://mcp.example.com/openbank-mcp/mcp`. See
[public-https-streamable-http.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/docs/public-https-streamable-http.md).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection drives a write tool | `AKAHU_READ_ONLY=true` by default; every write raises `ReadOnlyError` before any HTTP call. With writes on, each call asks the user to confirm. The prompt lists every value sent, each double-quoted with quotes, backslashes, newlines, control and invisible characters escaped; values over 1,000 characters are refused rather than truncated. Missing values are collected before the prompt, so one confirmation covers the final request. |
| Forged or replayed consent on 2026-07-28 connections | The server issues a single-use nonce bound to a SHA-256 digest of the exact prompt text, valid for 600 seconds, with at most 256 pending. A retry with different values, an expired nonce or a reused nonce is asked again. |
| Automation bypass widens the write surface | `AKAHU_AUTOMATION_BYPASS=true` skips the prompt only for `acct_refresh_all_accounts` and `acct_refresh_account`. Support tickets and name checks always prompt. Startup is refused when bypass is on while read-only is on. The startup banner lists bypass-eligible tools, and each skipped prompt is logged at INFO. |
| Model-supplied IDs rewrite the request path | Account and transaction IDs are percent-encoded as a single path segment, so `/` or `..` cannot reach another endpoint. Empty IDs are rejected. |
| Token leakage via logs or errors | Tokens are `SecretStr`, hidden from reprs, and settings validation errors hide input. The client logs method, path and status (paths include Akahu account and transaction IDs), plus transport error class names. It never logs tokens, query parameters or response bodies. `httpx`, `httpcore` and `uvicorn.access` loggers are held at WARNING, and the uvicorn access log is off in HTTP mode. |
| Malicious env file in a cloned repo | No `.env` is read from the working directory. An env file is loaded only when `AKAHU_ENV_FILE` names an absolute path. On POSIX it must be owned by root or the current user and not writable by group or others. Process environment values take precedence over the file. |
| Base URL redirection exfiltrates Akahu tokens | `AKAHU_BASE_URL` must be HTTPS to `api.akahu.io` (port 443), with no credentials, query, fragment, whitespace or control characters. Another host requires `AKAHU_ALLOW_CUSTOM_BASE_URL=true` in the process environment; an env file cannot set it. The server logs a warning at startup when the host is not Akahu. |
| Retries duplicate non-idempotent writes | GETs, the batch ID lookup and refreshes retry up to 3 times on 5xx and transport errors. Support tickets and name checks are sent once, because a timed-out POST may already have taken effect. HTTP 429 is retried for all requests (Akahu did not process them), with `Retry-After` capped at 60 seconds. |
| Unauthenticated HTTP access | Every HTTP MCP request requires auth; unauthenticated calls get HTTP 401. Bearer tokens must be at least 32 visible ASCII characters with at least 10 distinct characters. |
| Open redirect or code theft via dynamic client registration | Client redirect URIs must match an allowlist. Defaults are the Claude, ChatGPT and Cursor connector callbacks plus `http://localhost:*` and `http://127.0.0.1:*`. Configured entries must be `https` with an exact path and no wildcard in the host or path, or plain `http` on a loopback host. Google's consent screen stays on. |
| Unauthorized Google account obtains a session | Access requires `email_verified` plus an exact email match, or a hosted-domain (`hd`) claim match for Workspace accounts. The check runs before the proxy stores tokens, so a refused code is deleted and leaves nothing at rest. Every request's access token is checked again. Startup fails without an allowlist. |
| Theft of OAuth state at rest | State is Fernet-encrypted with a key derived from the JWT signing key, in a directory kept at mode 0700. Expired entries are culled at startup and hourly. Rotating the signing key makes old entries undecryptable; they are read as misses. |
| Weak OAuth secrets | The signing key must be at least 32 bytes with at least 10 distinct characters. The Google client secret must be non-empty, and the public base URL must be HTTPS without a query or fragment. |
| Network exposure of the HTTP listener | Default bind is `127.0.0.1`. The guides require loopback, or a firewalled private interface when the proxy is on another host. The systemd unit runs as a dynamic user under `ProtectSystem=strict`, `NoNewPrivileges`, an empty capability set, a system-call filter and `UMask=0077`. |
| Secrets readable by other services | Templates keep Akahu tokens in `nz-openbank.env` (root:group 0640) and HTTP secrets in `nz-openbank-http.env` (root:root 0600), loaded only by the HTTP unit. |
| Supply chain compromise | `uv.lock` pins dependencies with hashes; CI runs `uv sync --locked`, `pip-audit --strict --require-hashes` on the exported lock, `bandit`, CodeQL and a weekly scheduled run. Actions are pinned to commit SHAs and linted with `actionlint` and `zizmor`. Releases require a `v*` tag on `main` with a passing CI run, publish to PyPI via Trusted Publishing (OIDC) behind a reviewer-gated environment, and attach build provenance to the wheel, sdist, `.mcpb` and container image. Plugin and extension launch specs pin the exact package version. |

## Residual risks and non-goals

- **The Personal App token reads everything connected.** Akahu Personal Apps
  have no finer-grained scopes. This server has no per-account allowlist, so
  any read tool can reach any connected account.
- **The LLM sees whatever data the user asks for.** Tool results, including
  balances, descriptions and masked account numbers, go to the MCP client and
  model provider. The provider's retention policy applies, and this server
  cannot control it.
- **Consent depends on the MCP client.** The server sends the prompt, but the
  client renders it and returns the answer. A buggy or malicious client that
  hides the prompt or auto-accepts defeats the second safety layer. Read-only
  mode is the only control that does not depend on the client.
- **Prompt injection still steers reads.** Injected text in transaction data
  can influence which read tools the model calls and what it says about the
  results.
- **Host compromise is out of scope.** An attacker with access to the process
  environment, env files, memory, or the state directory plus the signing key
  (including backups) can read every secret listed above.
- **Shared Akahu identity in HTTP mode.** Every allowlisted user or bearer
  holder acts as the same Akahu user, with no per-user separation.
- **No application-level rate limiting.** The server adds no request or
  auth-attempt rate limiting of its own. Apply limits at the reverse proxy if
  needed.
- **Platform-level redirect allowlist.** The default callbacks admit any
  account on those platforms. The Google allowlist and the consent screen are
  the controls that keep strangers out.
- **Transitive dependencies on install.** `uvx` installs resolve dependencies
  within the `pyproject.toml` ranges at install time, not from `uv.lock`. The
  container image is built from `uv.lock`.
- **Single-process consent state.** Pending consent nonces live in process
  memory, so the HTTP server must run as one process. A retry that lands on
  another worker is refused.
- **Debug logging.** `AKAHU_LOG_LEVEL=DEBUG` raises the verbosity of
  third-party libraries other than the HTTP client loggers. Keep `INFO` in
  production.
- **Akahu and banks.** Vulnerabilities in the Akahu API or connected banks are
  out of scope; report those to Akahu.

## Reporting

Report vulnerabilities privately as described in
[SECURITY.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/SECURITY.md).
For revoking and rotating exposed credentials, see
[secrets-operations.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/docs/secrets-operations.md).
