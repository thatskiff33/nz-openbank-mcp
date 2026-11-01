"""Per-process AkahuClient cache.

Tools call `get_client()` to obtain a shared async HTTP client. The first call
constructs it; subsequent calls reuse the same instance.
"""

from __future__ import annotations

from nz_openbank_mcp.client import AkahuClient
from nz_openbank_mcp.config import get_config

_client: AkahuClient | None = None


def get_client() -> AkahuClient:
    """Return the process-wide AkahuClient, constructing on first use."""
    global _client  # noqa: PLW0603 - one shared connection pool per process
    if _client is None:
        _client = AkahuClient(get_config())
    return _client


async def aclose_client() -> None:
    """Tear down the shared client. Called when the root server's lifespan ends."""
    global _client  # noqa: PLW0603 - one shared connection pool per process
    if _client is not None:
        await _client.aclose()
        _client = None
