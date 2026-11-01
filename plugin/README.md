# nz-openbank-mcp (Claude Code plugin)

This plugin packages [`nz-openbank-mcp`](https://github.com/thatskiff33/nz-openbank-mcp) for installation in **Claude Code** via this repo's plugin marketplace. It exposes 14 MCP tools for the Akahu open-finance API (NZ), with credentials prompted at install and stored in your OS keychain (macOS Keychain on macOS, Windows Credential Manager on Windows). See the [main repo README](https://github.com/thatskiff33/nz-openbank-mcp#readme) for tool reference and architecture details.

> **Claude Desktop users:** use the `.mcpb` Desktop Extension instead - see the [main README](https://github.com/thatskiff33/nz-openbank-mcp#install-in-claude-desktop). Claude Desktop has no UI to configure marketplace-plugin `userConfig` values ([anthropics/claude-code#39455](https://github.com/anthropics/claude-code/issues/39455), [#39827](https://github.com/anthropics/claude-code/issues/39827)).

## Prerequisites

1. **Akahu Personal App + User token** - register at https://my.akahu.nz/developers
2. **[`uv`](https://docs.astral.sh/uv/)** on `PATH` so `uvx` can launch the server
3. **Claude Code** (v2.1.83 or later)

## Install in Claude Code

```text
/plugin marketplace add thatskiff33/nz-openbank-mcp
/plugin install nz-openbank-mcp@nz-openbank
```

You will be prompted for four values:

| Field | What it is | Default |
| --- | --- | --- |
| Akahu User Token | User token from the Akahu developer console | (none) |
| Akahu App Token | App token from the Akahu developer console | (none) |
| Read-only mode | `true` refuses every write tool | `true` |
| Automation bypass | `true` skips consent for safe writes (refresh only) | `false` |

The two tokens are stored in your OS keychain (macOS Keychain / Windows Credential Manager); they never land in plaintext config. The safety defaults give you a read-only server out of the box.

After install: `/mcp` should show `nz-openbank-mcp` connected. Ask Claude *"what accounts do I have?"* to confirm tokens reached the server.

### Reconfigure later

`/plugin` -> Installed -> nz-openbank-mcp -> Configure options. Useful for flipping `read-only` to `false` when you need a refresh, then back to `true`.

## Verifying the install

- `/mcp` lists `nz-openbank-mcp` as connected
- Ask Claude to run a read tool (e.g. `acct_list_accounts`): it returns masked account details
- With defaults (`read-only=true`), any write tool refuses with `ReadOnlyError` before any HTTP call

## Updating

```text
/plugin marketplace update nz-openbank
```

The plugin launches the PyPI release pinned in `.mcp.json` (`uvx --from nz-openbank-mcp==X.Y.Z`). Run the marketplace update above to move to a newer release.

## Uninstall

```text
/plugin uninstall nz-openbank-mcp@nz-openbank
```

Removes the userConfig values from your OS keychain.

## Manual install (non-plugin path)

If you'd rather wire the server yourself with `claude mcp add` or `claude_desktop_config.json`, see the install sections in the [main repo README](https://github.com/thatskiff33/nz-openbank-mcp#readme).
