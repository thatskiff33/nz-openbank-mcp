"""Shared MCP tool metadata for ChatGPT Apps SDK compatibility."""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_ANNOTATIONS = ToolAnnotations(read_only_hint=True)

NON_DESTRUCTIVE_WRITE_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    open_world_hint=False,
)

IDEMPOTENT_WRITE_ANNOTATIONS = NON_DESTRUCTIVE_WRITE_ANNOTATIONS.model_copy(
    update={"idempotent_hint": True}
)
