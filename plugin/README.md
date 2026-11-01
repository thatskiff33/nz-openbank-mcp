# nz-openbank-mcp plugin

This directory is the plugin that Claude Code, Codex, Cursor and Grok Build
install from this repo's marketplaces. It starts the
[`nz-openbank-mcp`](https://github.com/thatskiff33/nz-openbank-mcp) server
with `uvx` and gives your assistant 14 Akahu tools, read-only until you say
otherwise. The [main README](https://github.com/thatskiff33/nz-openbank-mcp#readme)
lists the tools and settings.

For Claude Desktop, use the `.mcpb` extension from the
[latest release](https://github.com/thatskiff33/nz-openbank-mcp/releases/latest)
instead. Desktop cannot yet collect plugin settings
([anthropics/claude-code#39455](https://github.com/anthropics/claude-code/issues/39455)).

## Claude Code

You need Claude Code 2.1.83 or later, `uv` on your `PATH`, and the App and
User Tokens from your Akahu Personal App
([my.akahu.nz/developers](https://my.akahu.nz/developers)).

```text
/plugin marketplace add thatskiff33/nz-openbank-mcp
/plugin install nz-openbank-mcp@nz-openbank
```

Claude Code then asks for:

| Setting | Default | Notes |
| --- | --- | --- |
| Akahu User Token | none | Kept in the OS keychain |
| Akahu App Token | none | Kept in the OS keychain |
| Read-only mode | `true` | `false` lets write tools run, each with a confirmation prompt |
| Automation bypass | `false` | `true` skips the prompt for the two refresh tools only |

To check it worked, run `/mcp` and look for the server, then ask for your
account list. Asking for a refresh should be refused while read-only mode is
on.

| Task | Command |
| --- | --- |
| Change settings | `/plugin`, pick **nz-openbank-mcp**, then **Configure options** |
| Move to a newer release | `/plugin marketplace update nz-openbank` |
| Remove (also clears the stored tokens) | `/plugin uninstall nz-openbank-mcp@nz-openbank` |

Each plugin version launches one pinned PyPI release, so updating the
marketplace is how you get a newer server.

## Codex, Cursor and Grok Build

```bash
codex plugin marketplace add thatskiff33/nz-openbank-mcp
codex plugin add nz-openbank-mcp@nz-openbank

agent plugin marketplace add https://github.com/thatskiff33/nz-openbank-mcp
# then install nz-openbank-mcp from Customize in Cursor

grok plugin marketplace add thatskiff33/nz-openbank-mcp
grok plugin install nz-openbank-mcp --trust
```

Cursor takes the tokens under **Plugins -> Configure**. Codex and Grok Build
read `AKAHU_USER_TOKEN` and `AKAHU_APP_TOKEN` from the environment they start
in; the [main README](https://github.com/thatskiff33/nz-openbank-mcp#codex-grok-build)
shows how to load them from your OS secret store.

## Editing

The JSON manifests here are generated. Change `plugin.base.toml`, then run
`uv run --no-project python scripts/sync_plugin_manifests.py` from the repo
root.
