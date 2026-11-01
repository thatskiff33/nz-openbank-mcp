"""Tests for the concurrency helper."""

from __future__ import annotations

import asyncio

import pytest


async def test_pair_returns_both_results() -> None:
    from nz_openbank_mcp.aio import pair

    async def value(v: int) -> int:
        await asyncio.sleep(0)
        return v

    assert await pair(value(1), value(2)) == (1, 2)


async def test_pair_raises_the_failure_and_cancels_the_other() -> None:
    from nz_openbank_mcp.aio import pair

    cancelled = asyncio.Event()

    async def fails() -> int:
        await asyncio.sleep(0)
        raise LookupError("not found")

    async def slow() -> int:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 0  # pragma: no cover

    with pytest.raises(LookupError, match="not found"):
        await pair(fails(), slow())
    assert cancelled.is_set()
