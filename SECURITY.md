# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub:
[Report a vulnerability](https://github.com/thatskiff33/nz-openbank-mcp/security/advisories/new).

Please do not open a public issue, pull request or discussion for a suspected
vulnerability. Include the affected version, how the server was launched (stdio
plugin, Desktop Extension, or HTTP mode), and steps to reproduce.

Never include real Akahu tokens, bearer tokens, OAuth secrets, account numbers,
or transaction data in a report. Use synthetic values; if a real credential was
exposed, revoke it first (see [docs/secrets-operations.md](docs/secrets-operations.md)).

Expect an acknowledgement within 7 days. Fixes are released as a new patch
version and described in a GitHub Security Advisory once users can upgrade.

## Supported versions

Only the latest release on PyPI and GitHub Releases receives security fixes.
Upgrade before reporting if you are on an older version.

## Security model

The [threat model](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/docs/threat-model.md) covers assets, trust
boundaries, mitigations and residual risks in detail.

- **Read-only by default.** `AKAHU_READ_ONLY=true` makes every write tool refuse
  before any network call.
- **Consent-gated writes.** With writes enabled, each write asks the user to
  confirm through the MCP host. `AKAHU_AUTOMATION_BYPASS=true` skips the prompt
  only for the account-refresh tools, and is rejected while read-only is on.
- **Pinned upstream.** Akahu tokens are only sent to `https://api.akahu.io`
  unless `AKAHU_ALLOW_CUSTOM_BASE_URL=true` is set in the process environment.
  The server never reads a `.env` file from the working directory.
- **Local by default.** The stdio server (plugin and Desktop Extension) has no
  network listener. Tokens come from the host's keychain-backed settings.
- **HTTP mode** is opt-in and requires authentication:
  - `bearer`: a static token of at least 32 characters, compared in constant time.
  - `oauth`: the server is the OAuth authorization server with Google as the
    identity provider. Access is limited to allowlisted verified emails or
    Google Workspace domains (hosted-domain claim); client redirect URIs are
    limited to an allowlist (the Claude, ChatGPT and Cursor connector callbacks
    and loopback by default); tokens are signed with an explicit key and OAuth
    state is stored encrypted.
- **No logging of secrets or financial data.** Tokens are held as secret types,
  hidden from reprs and validation errors. Balances and transaction contents
  are not logged; request paths, which can include Akahu account and
  transaction IDs, are.

## Out of scope

- Vulnerabilities in the Akahu API or the banks behind it; report those to
  Akahu.
- Issues that require an attacker who already controls the server's process
  environment, env file, or host.
