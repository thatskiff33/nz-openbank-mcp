"""Concurrency helper for tools that make independent Akahu requests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


async def pair[A, B](first: Coroutine[Any, Any, A], second: Coroutine[Any, Any, B]) -> tuple[A, B]:
    """Await two coroutines concurrently; if one fails, cancel the other.

    Raises the first failure itself rather than an ExceptionGroup, so tool
    errors read the same as a single sequential call.
    """
    try:
        async with asyncio.TaskGroup() as tg:
            a = tg.create_task(first)
            b = tg.create_task(second)
    except ExceptionGroup as group:
        raise group.exceptions[0] from None
    return a.result(), b.result()
