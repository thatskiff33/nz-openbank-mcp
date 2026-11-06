# Changelog

Notable changes per release. Full notes and downloads are on the
[Releases page](https://github.com/thatskiff33/nz-openbank-mcp/releases).
Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- The systemd templates keep the OpenAI tunnel values in a new `/etc/nz-openbank-mcp/nz-openbank-tunnel.env` (root:root 0600), loaded only by the tunnel unit, so the HTTP server no longer receives the OpenAI key. Before installing the new tunnel unit, move `CONTROL_PLANE_TUNNEL_ID`, `CONTROL_PLANE_API_KEY`, `LOG_LEVEL` and `LOG_FORMAT` out of `nz-openbank.env` into that file; the new unit fails to start until it exists. The tunnel unit also gains the HTTP unit's system-call filter and `ProcSubset=pid`, and the Caddy example now forwards only the routes the server serves, with a 1MB request body limit.
- **Breaking for HTTP bearer mode behind a proxy.** The HTTP entrypoint now checks the `Host` and `Origin` headers of every request before authentication. Loopback is always accepted, and OAuth mode also accepts the host of `NZ_OPENBANK_MCP_PUBLIC_BASE_URL`. In bearer mode behind a reverse proxy, set the new `NZ_OPENBANK_MCP_ALLOWED_HOSTS` to the public host name, or requests get HTTP 421.
- Tool annotations now set every hint explicitly. Reads and the two refreshes declare `openWorldHint: false`; `txn_report_transaction_issue` and `id_verify_name`, which reach a person at Akahu or your bank, declare `openWorldHint: true`. The startup banner and bypass log now name tools as hosts call them, for example `acct_refresh_account`. The support-ticket tool's description asks for `fields` and `other_transaction_id` as arguments instead of promising a prompt.
- Account numbers are now shown in full by default. Set `AKAHU_MASK_ACCOUNTS=true` (a new setting in every host's install form) to mask them to the bank code, last four digits and suffix as before. Transaction descriptions and merchant names were never masked, and the docs now say so.
- Display name is now "NZ Open Banking MCP (Akahu)" in every plugin, extension and registry manifest.
- `txn_get_transactions` and `txn_search_transactions` return `limit_reached: true` when the result holds `limit` items and more may exist. Before, a range with more transactions than `limit` came back looking complete.
- An account balance with no currency is reported as `currency: null` instead of being assumed to be NZD.
- `txn_get_transactions` and `txn_search_transactions` look up account currencies while the first page loads, saving one round trip.
- Akahu ids are validated before any request is sent or any confirmation is asked; a value that is not a plain Akahu id is refused.
- Akahu error responses now say what to do: a 401 points at the two tokens, a 403 on a name check points at the Personal App scope, and rate-limit and server errors say to wait. Response bodies are never included.
- A malformed Akahu response is reported by field name and error type only. Response values, such as balances, no longer appear in tool errors or logs.

## 0.1.6 - 2026-11-02

- GitHub Releases are created by the release workflow with the wheel, sdist and `.mcpb` attached before publishing, since releases are immutable once published.
- Same package contents as 0.1.5.

## 0.1.5 - 2026-11-02

The 0.1.5 GitHub Release has no files attached. Its package is on PyPI and GHCR; for the `.mcpb`, use 0.1.6.

- The FastMCP startup banner is no longer printed by either entrypoint.
- The Cursor agents OAuth callback is in the default HTTP redirect allowlist.
- Container image on GHCR (`ghcr.io/thatskiff33/nz-openbank-mcp`) for amd64 and arm64, read-only by default, with build provenance.
- Release files carry GitHub build provenance; verify with `gh attestation verify`.
- CI runs on Linux, macOS and Windows, plus OpenSSF Scorecard and CodeQL.
- Added a threat model, privacy policy, code of conduct and support guide.
- Plugin and extension manifests gain icons, a tool list, privacy and support links, and the Finance category.

## 0.1.4 - 2026-11-01

- New README with install buttons, example prompts and a safety summary; also the PyPI description.
- Listed on the official MCP Registry as `io.github.thatskiff33/nz-openbank-mcp`, published from each release.

## 0.1.3 - 2026-11-01

- OAuth: refused Google accounts are rejected before any upstream tokens are stored; expired OAuth state is culled hourly; low-diversity bearer tokens and signing keys are rejected.
- Deployment: HTTP-only secrets moved to `nz-openbank-http.env`, and `nz-openbank-http.service` runs under its own dynamic user with state in `/var/lib/nz-openbank-http`.
- Akahu client: only idempotent requests are retried, malformed responses raise clear errors, and transaction paging is capped with a `truncated` flag.
- Write consent prompts quote and escape every value and are bound to the exact prompt text.
- Money values are exact decimals end to end.
- Plugins for Claude Code, Codex, Cursor and Grok.

## 0.1.2 - 2026-11-01

- Pending transactions no longer crash, and are returned marked `"pending": true`.
- Dates are New Zealand calendar days, and date-only filters cover the whole NZ day.
- Amounts use each account's currency; unknown currency gives `currency: null`.
- Account masking fails closed for non-NZ formats.
- `limit` is 1 to 500, `issue_type` is an enum, and `txn_search_transactions` takes `start_date` and `end_date`.

## 0.1.1 - 2026-11-01

- The Claude Code plugin and Desktop Extension launch the PyPI release instead of `main`.
- `SECURITY.md`, issue and PR templates, and the Trusted Publishing release workflow.

## 0.1.0 - 2026-11-01

- First release on PyPI: 14 tools over the Akahu Personal App API, read-only by default, with consent-gated writes.
- HTTP mode with bearer or Google OAuth, a redirect allowlist, an explicit signing key and encrypted durable storage.
