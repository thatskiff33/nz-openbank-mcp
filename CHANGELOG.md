# Changelog

Notable changes per release. Full notes and downloads are on the
[Releases page](https://github.com/thatskiff33/nz-openbank-mcp/releases).
Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- New install route: the npm package `nz-openbank-mcp`
  (`npx -y nz-openbank-mcp@X.Y.Z`), a launcher with no dependencies that runs
  the PyPI release of the same version with `uvx`, so it still needs `uv`. It
  is published from the release workflow by trusted publishing, with
  provenance, and listed in the MCP Registry entry. The plugins, the Desktop
  Extension and the container image are unchanged.

## 0.1.7 - 2026-11-07

### Upgrading from 0.1.6

- **Breaking: HTTP deployments reached by a non-loopback host name.** The HTTP entrypoint now checks the `Host` and `Origin` headers of every request before authentication. It accepts `localhost`, `127.0.0.1` and `::1`, the local IP address the request arrived on, the names in the new `NZ_OPENBANK_MCP_ALLOWED_HOSTS`, and, in OAuth mode, the host of `NZ_OPENBANK_MCP_PUBLIC_BASE_URL`. Before upgrading, if clients reach the server by any other name (through a reverse proxy in bearer mode, a proxy that rewrites `Host`, a LAN host name or a Docker network name), add that name to `NZ_OPENBANK_MCP_ALLOWED_HOSTS`, or every request gets HTTP 421. stdio, local HTTP and OAuth deployments reached at their public base URL need no change.
- **Browser-based clients on a public deployment are refused.** A request to a non-loopback host whose `Origin` is neither `https://` plus an accepted host nor the request's own scheme and host gets HTTP 403, so a browser page from another site cannot connect to a public deployment. Server-side connectors, which send no `Origin`, are unaffected.
- **Account numbers are now shown in full by default.** To keep the old masking (bank code, last four digits and suffix), set `AKAHU_MASK_ACCOUNTS=true`. It is a new setting in the Claude Code, Cursor and Desktop Extension install settings; Codex and Grok Build read it from the environment. An empty or unfilled value means the default, so existing installs keep starting. The startup log now says whether account numbers are masked. Transaction descriptions and merchant names were never masked.
- **systemd deployments.** The templates keep the OpenAI tunnel values in a new `/etc/nz-openbank-mcp/nz-openbank-tunnel.env` (root:root 0600), loaded only by the tunnel unit, so the HTTP server no longer receives the OpenAI key. Before installing the new tunnel unit, move `CONTROL_PLANE_TUNNEL_ID`, `CONTROL_PLANE_API_KEY`, `LOG_LEVEL` and `LOG_FORMAT` out of `nz-openbank.env` into that file; the new unit fails to start until it exists. The tunnel unit also gains the HTTP unit's sandbox settings, including its system-call filter and `ProcSubset=pid`, and the Caddy example now forwards only the routes the server serves, with a 1MB request body limit.
- **Building the container image from a checkout** now needs the wheel first: `uv build --wheel --build-constraints .github/build-constraints/requirements.txt --require-hashes`, then `docker build .`. Published images are unaffected.

### Other changes

- `NZ_OPENBANK_MCP_ALLOWED_HOSTS` entries and the host in `NZ_OPENBANK_MCP_PUBLIC_BASE_URL` must be a plain `host` or `host:port`, with a port from 1 to 65535 (punycode for international names); anything else stops the server at startup. The HTTP startup log lists the accepted hosts and warns when only loopback is accepted.
- `examples/claude_desktop_config.json` now pins the release (`uvx --from nz-openbank-mcp==X.Y.Z`) and is generated with the manifests.
- Releases check the CHANGELOG section and build the `.mcpb` before anything is published to PyPI, build the package with a hash-pinned build backend, and verify every file in the `.mcpb` against `mcpb/`. The container image installs that same wheel, checked against PyPI, instead of building the package during the image build.
- Tool annotations now set every hint explicitly. Reads and the two refreshes declare `openWorldHint: false`; `txn_report_transaction_issue` and `id_verify_name`, which reach a person at Akahu or your bank, declare `openWorldHint: true`. The startup banner and bypass log now name tools as hosts call them, for example `acct_refresh_account`. The support-ticket tool's description asks for `fields` and `other_transaction_id` as arguments instead of promising a prompt.
- Display name is now "NZ Open Banking MCP (Akahu)" in the Codex plugin and marketplace, the Claude Desktop Extension and the MCP Registry entry.
- `txn_get_transactions` and `txn_search_transactions` return `limit_reached: true` whenever the result holds `limit` items, since more may exist. Before, a range with more transactions than `limit` came back looking complete.
- An account with no reported currency now has `currency: null`, and its balances and transactions are shown as bare numbers without a currency symbol, instead of being assumed to be NZD.
- `txn_get_transactions` and `txn_search_transactions` look up account currencies while the first page loads, saving one round trip.
- Akahu ids are validated before any request that uses them is sent and before any confirmation is asked; a value that is not a plain Akahu id is refused.
- Akahu error responses now say what to do: a 401 points at the two tokens, a 403 on a name check points at the Personal App scope, and rate-limit and server errors say to wait. Response bodies are never included.
- A malformed Akahu response is reported by field name and error type only. Response values, such as balances, no longer appear in tool errors or logs.
- The test suite runs from the sdist; tests of repository-only packaging files are skipped there.

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
- Deployment: HTTP-only secrets moved to `nz-openbank-http.env`, and `nz-openbank-http.service` runs under its own dynamic user with state in `/var/lib/nz-openbank-http`. To upgrade from 0.1.2 or earlier, move the `NZ_OPENBANK_MCP_*` values into `nz-openbank-http.env`, install the new unit, then delete the old OAuth state (`sudo rm -rf /var/lib/nz-openbank-mcp/oauth-proxy /var/lib/nz-openbank-mcp/fastmcp /var/lib/nz-openbank-mcp/.local/share/fastmcp`); connectors sign in again afterwards.
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
