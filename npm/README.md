# nz-openbank-mcp (npm launcher)

Unofficial MCP server for the [Akahu](https://www.akahu.nz) open-finance API
(New Zealand). Read-only by default, and it asks before every write. Not
affiliated with Akahu or any bank.

The server is a Python package on [PyPI](https://pypi.org/project/nz-openbank-mcp/).
This npm package is a small launcher for it: `npx -y nz-openbank-mcp@X.Y.Z` runs
`uvx --from nz-openbank-mcp==X.Y.Z nz-openbank-mcp`, the PyPI release with the
same version. It has no dependencies and no install scripts.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which provides
  `uvx` and downloads a suitable Python if needed.
- Node.js 22 or later, for `npx`.
- An Akahu Personal App: a user token and an app token.

## Use

```json
{
  "mcpServers": {
    "akahu": {
      "command": "npx",
      "args": ["-y", "nz-openbank-mcp@X.Y.Z"],
      "env": {
        "AKAHU_USER_TOKEN": "user_token_REPLACE_ME",
        "AKAHU_APP_TOKEN": "app_token_REPLACE_ME"
      }
    }
  }
}
```

Replace `X.Y.Z` with a published version so the server does not change under
you. `nz-openbank-mcp-http` starts the authenticated Streamable HTTP server
the same way.

Settings, the tool list, the safety model and the other install routes
(Claude Code and other plugins, the Claude Desktop Extension, Docker) are in
the [project README](https://github.com/thatskiff33/nz-openbank-mcp#readme).

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
