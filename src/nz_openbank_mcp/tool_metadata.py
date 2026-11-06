"""Tool annotations, with every hint set so nothing depends on MCP defaults.

open_world_hint is True only for tools that reach a person or system beyond
the user's own Akahu data.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

# Asks Akahu to re-sync the user's own accounts; repeat calls add nothing.
REFRESH_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

# Reaches outside the user's data (a support agent, a bank identity check),
# and each call is a new request.
OPEN_WORLD_WRITE_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
