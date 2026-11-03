# Changelog

Notable changes per release. Full notes and downloads are on the
[Releases page](https://github.com/thatskiff33/nz-openbank-mcp/releases).
Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- Display name is now "NZ Open Banking MCP (Akahu)" in every plugin, extension and registry manifest.

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
