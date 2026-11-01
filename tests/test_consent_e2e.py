"""End-to-end write consent through a real FastMCP client, both protocol eras."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.exceptions import ToolError

from nz_openbank_mcp import deps

MODES = [("legacy", "2025-11-25"), ("auto", "2026-07-28")]


def _handler(action: str, prompts: list[str]) -> Any:
    async def handle(message: str, response_type: Any, params: Any, context: Any) -> Any:
        prompts.append(message)
        return ElicitResult(action=action, content={} if action == "accept" else None)

    return handle


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    deps._client = None


@pytest.mark.parametrize(("mode", "version"), MODES)
async def test_accept_runs_write(
    writable_env: None, respx_mock: respx.MockRouter, mode: str, version: str
) -> None:
    from nz_openbank_mcp.server import build_server

    route = respx_mock.post("/refresh/acc_1").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    prompts: list[str] = []
    handler = _handler("accept", prompts)
    async with Client(build_server(), elicitation_handler=handler, mode=mode) as c:
        assert c.protocol_version == version
        result = await c.call_tool("acct_refresh_account", {"account_id": "acc_1"})

    assert route.call_count == 1
    assert prompts == ["Confirm: Refresh data for account acc_1. Rate-limited by your bank."]
    assert result.structured_content is not None


@pytest.mark.parametrize(("mode", "version"), MODES)
@pytest.mark.parametrize(("action", "word"), [("decline", "declined"), ("cancel", "cancelled")])
async def test_decline_or_cancel_blocks_write(
    writable_env: None,
    respx_mock: respx.MockRouter,
    mode: str,
    version: str,
    action: str,
    word: str,
) -> None:
    from nz_openbank_mcp.server import build_server

    route = respx_mock.post("/refresh/acc_1").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    prompts: list[str] = []
    handler = _handler(action, prompts)
    async with Client(build_server(), elicitation_handler=handler, mode=mode) as c:
        assert c.protocol_version == version
        with pytest.raises(ToolError, match=f"User {word}"):
            await c.call_tool("acct_refresh_account", {"account_id": "acc_1"})

    assert route.call_count == 0
    assert len(prompts) == 1
