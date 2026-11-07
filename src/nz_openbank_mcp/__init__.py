"""Unofficial MCP server for the Akahu open-finance API (New Zealand)."""

import os

# FastMCP's own settings read ./.env at import unless told otherwise; a cloned
# project must not be able to configure the server through its working directory.
os.environ.setdefault("FASTMCP_ENV_FILE", os.devnull)

__version__ = "0.1.8"
