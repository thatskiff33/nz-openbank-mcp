"""Write consent on 2026-07-28 connections: InputRequiredResult round trip."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError
from mcp.types import ElicitResult, InputRequiredResult

from nz_openbank_mcp import safety


def _ctx(state: str | None = None, responses: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(protocol_version="2026-07-28"),
        request_state=state,
        input_responses=responses,
        elicit=AsyncMock(side_effect=AssertionError("must not push elicitation")),
    )


@pytest.fixture(autouse=True)
def _clear_pending() -> Iterator[None]:
    safety._PENDING.clear()
    yield
    safety._PENDING.clear()


async def _ask() -> str:
    ask = await safety.confirm_write(_ctx(), "Refresh account a1.")
    assert isinstance(ask, InputRequiredResult)
    assert ask.request_state is not None
    return ask.request_state


async def test_first_round_returns_consent_request() -> None:
    ask = await safety.confirm_write(_ctx(), "Refresh account a1.")

    assert isinstance(ask, InputRequiredResult)
    assert ask.input_requests is not None
    request = ask.input_requests["consent"]
    assert request.method == "elicitation/create"
    assert request.params.message == "Confirm: Refresh account a1."
    assert ask.request_state is not None
    assert ask.request_state.startswith("consent:")


async def test_accept_with_issued_nonce_proceeds() -> None:
    state = await _ask()
    ctx = _ctx(state, {"consent": ElicitResult(action="accept", content={})})

    assert await safety.confirm_write(ctx, "Refresh account a1.") is None


async def test_nonce_is_single_use() -> None:
    state = await _ask()
    accept = {"consent": ElicitResult(action="accept", content={})}
    assert await safety.confirm_write(_ctx(state, accept), "x") is None

    replay = await safety.confirm_write(_ctx(state, accept), "x")
    assert isinstance(replay, InputRequiredResult)


@pytest.mark.parametrize("state", [None, "consent:forged", "other:state"])
async def test_accept_without_issued_nonce_asks_again(state: str | None) -> None:
    accept = {"consent": ElicitResult(action="accept", content={})}

    ask = await safety.confirm_write(_ctx(state, accept), "x")

    assert isinstance(ask, InputRequiredResult)


async def test_expired_nonce_asks_again(monkeypatch: pytest.MonkeyPatch) -> None:
    state = await _ask()
    nonce = state.removeprefix("consent:")
    safety._PENDING[nonce] = 0.0
    accept = {"consent": ElicitResult(action="accept", content={})}

    ask = await safety.confirm_write(_ctx(state, accept), "x")

    assert isinstance(ask, InputRequiredResult)


async def test_decline_raises() -> None:
    state = await _ask()
    ctx = _ctx(state, {"consent": ElicitResult(action="decline")})

    with pytest.raises(safety.ElicitationDeclinedError, match="User declined: x") as exc:
        await safety.confirm_write(ctx, "x")
    assert not isinstance(exc.value, safety.ElicitationCancelledError)


@pytest.mark.parametrize(
    "responses",
    [None, {}, {"consent": ElicitResult(action="cancel")}, {"consent": "accept"}],
)
async def test_cancel_or_missing_answer_raises_cancelled(responses: Any) -> None:
    state = await _ask()

    with pytest.raises(safety.ElicitationCancelledError, match="User cancelled: x"):
        await safety.confirm_write(_ctx(state, responses), "x")


def test_issue_prunes_expired_and_caps_size(monkeypatch: pytest.MonkeyPatch) -> None:
    safety._PENDING["old"] = 0.0
    safety._issue_nonce()
    assert "old" not in safety._PENDING

    monkeypatch.setattr(safety, "_PENDING_MAX", 3)
    safety._PENDING.clear()
    first = safety._issue_nonce()
    for _ in range(3):
        safety._issue_nonce()
    assert len(safety._PENDING) == 3
    assert first not in safety._PENDING


async def test_elicit_value_refuses_on_modern_protocol() -> None:
    with pytest.raises(ToolError, match="pass it as a tool argument"):
        await safety.elicit_value(_ctx(), "Provide the id:", str)


async def test_write_tool_returns_ask_without_calling_body(writable_env: None) -> None:
    body = AsyncMock(return_value={"ok": True})

    @safety.require_write_consent("Do {thing}.")
    async def tool(*, ctx: Any, thing: str) -> dict[str, Any]:
        return await body(ctx=ctx, thing=thing)

    result = await tool(ctx=_ctx(), thing="it")

    assert isinstance(result, InputRequiredResult)
    body.assert_not_awaited()
