"""Tests for safety.py: ReadOnlyError, elicit gating, automation bypass."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest


async def test_confirm_write_proceeds_on_accept(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import confirm_write

    ctx = ctx_factory(elicit_action="accept")
    await confirm_write(ctx, "Do the thing?")
    ctx.elicit.assert_awaited_once()
    args, kwargs = ctx.elicit.call_args
    assert "Do the thing?" in args[0]


async def test_confirm_write_raises_on_decline(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationDeclinedError, confirm_write

    ctx = ctx_factory(elicit_action="decline")
    with pytest.raises(ElicitationDeclinedError):
        await confirm_write(ctx, "Do the thing?")


async def test_confirm_write_raises_on_cancel(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationCancelledError, confirm_write

    ctx = ctx_factory(elicit_action="cancel")
    with pytest.raises(ElicitationCancelledError):
        await confirm_write(ctx, "Do the thing?")


async def test_confirm_write_passes_explicit_response_type(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    """Lock in the FastMCP 3.3 deprecation fix: never pass response_type=None."""
    from nz_openbank_mcp.safety import confirm_write

    ctx = ctx_factory(elicit_action="accept")
    await confirm_write(ctx, "Do the thing?")
    _, kwargs = ctx.elicit.call_args
    assert kwargs.get("response_type") is not None


def test_cancelled_error_is_a_declined_error() -> None:
    """Subclass relationship lets binary 'did the user consent?' handlers
    catch both outcomes via `except ElicitationDeclinedError`."""
    from nz_openbank_mcp.safety import (
        ElicitationCancelledError,
        ElicitationDeclinedError,
    )

    assert issubclass(ElicitationCancelledError, ElicitationDeclinedError)


async def test_require_write_consent_blocks_in_readonly(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    """fake_env defaults to read-only; the decorated tool must refuse."""
    from nz_openbank_mcp.safety import ReadOnlyError, require_write_consent

    @require_write_consent("Do the thing")
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2  # pragma: no cover  # why: should not run when read-only

    ctx = ctx_factory()
    with pytest.raises(ReadOnlyError) as exc_info:
        await my_tool(ctx=ctx, value=21)
    msg = str(exc_info.value)
    assert "AKAHU_READ_ONLY" in msg
    assert "AKAHU_AUTOMATION_BYPASS" in msg
    ctx.elicit.assert_not_awaited()


async def test_require_write_consent_elicits_and_runs(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import require_write_consent

    @require_write_consent("Do the thing")
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2

    ctx = ctx_factory(elicit_action="accept")
    result = await my_tool(ctx=ctx, value=21)
    assert result == 42
    ctx.elicit.assert_awaited_once()


async def test_require_write_consent_aborts_on_decline(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationDeclinedError, require_write_consent

    @require_write_consent("Do the thing")
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2  # pragma: no cover  # why: decline short-circuits

    ctx = ctx_factory(elicit_action="decline")
    with pytest.raises(ElicitationDeclinedError):
        await my_tool(ctx=ctx, value=21)


async def test_require_write_consent_aborts_on_cancel(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationCancelledError, require_write_consent

    @require_write_consent("Do the thing")
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2  # pragma: no cover  # why: cancel short-circuits

    ctx = ctx_factory(elicit_action="cancel")
    with pytest.raises(ElicitationCancelledError):
        await my_tool(ctx=ctx, value=21)


async def test_automatable_skips_elicit_when_bypass_on(
    bypass_env: None,
    ctx_factory: Callable[..., MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from nz_openbank_mcp.safety import require_write_consent

    @require_write_consent("Refresh things", automatable=True)
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2

    ctx = ctx_factory(elicit_action="decline")  # decline ignored when bypassed
    with caplog.at_level(logging.INFO, logger="nz_openbank_mcp.safety"):
        result = await my_tool(ctx=ctx, value=21)
    assert result == 42
    ctx.elicit.assert_not_awaited()
    assert any("[BYPASS]" in r.message and "my_tool" in r.message for r in caplog.records)


async def test_automatable_still_elicits_when_bypass_off(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import require_write_consent

    @require_write_consent("Refresh things", automatable=True)
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2

    ctx = ctx_factory(elicit_action="accept")
    result = await my_tool(ctx=ctx, value=21)
    assert result == 42
    ctx.elicit.assert_awaited_once()


async def test_non_automatable_still_elicits_when_bypass_on(
    bypass_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import require_write_consent

    @require_write_consent("Sensitive write", automatable=False)
    async def my_tool(*, ctx: Any, value: int) -> int:
        return value * 2

    ctx = ctx_factory(elicit_action="accept")
    result = await my_tool(ctx=ctx, value=21)
    assert result == 42
    ctx.elicit.assert_awaited_once()


def test_bypass_eligible_tools_registry(fake_env: None) -> None:
    """Decorator records its name iff automatable=True; non-automatable absent."""
    from nz_openbank_mcp import safety
    from nz_openbank_mcp.safety import bypass_eligible_tools, require_write_consent

    # Snapshot/restore to avoid polluting other tests that rely on real tool registrations.
    snapshot = set(safety._BYPASS_REGISTRY)  # noqa: SLF001
    try:

        @require_write_consent("auto thing", automatable=True)
        async def auto_thing(*, ctx: Any) -> None: ...  # pragma: no cover

        @require_write_consent("manual thing", automatable=False)
        async def manual_thing(*, ctx: Any) -> None: ...  # pragma: no cover

        names = bypass_eligible_tools()
        assert "auto_thing" in names
        assert "manual_thing" not in names
    finally:
        safety._BYPASS_REGISTRY.clear()  # noqa: SLF001
        safety._BYPASS_REGISTRY.update(snapshot)  # noqa: SLF001


def test_shown_quotes_and_escapes_layout_characters() -> None:
    from nz_openbank_mcp.safety import shown

    assert shown("plain") == '"plain"'
    assert shown('say "hi"\\') == '"say \\"hi\\"\\\\"'
    assert shown("line one\n- account: fake") == '"line one\\n- account: fake"'
    assert shown("tab\tcr\r") == '"tab\\tcr\\r"'


def test_shown_escapes_invisible_and_bidi_characters() -> None:
    from nz_openbank_mcp.safety import shown

    assert shown("a\u202eb") == '"a\\u202eb"'
    assert shown("zero\u200bwidth") == '"zero\\u200bwidth"'
    assert shown("bell\x07") == '"bell\\u0007"'
    assert shown("sep\u2028") == '"sep\\u2028"'
    assert shown("tag\U000e0041") == '"tag\\U000e0041"'


def test_shown_keeps_ordinary_unicode() -> None:
    from nz_openbank_mcp.safety import shown

    assert shown("Ng\u0101ti Wh\u0101tua") == '"Ng\u0101ti Wh\u0101tua"'


def test_shown_refuses_values_too_long_to_show() -> None:
    from fastmcp.exceptions import ToolError

    from nz_openbank_mcp.safety import MAX_SHOWN_CHARS, shown

    assert shown("x" * MAX_SHOWN_CHARS) == '"' + "x" * MAX_SHOWN_CHARS + '"'
    with pytest.raises(ToolError, match="shown in full"):
        shown("x" * (MAX_SHOWN_CHARS + 1))


def test_shown_refuses_non_text() -> None:
    from fastmcp.exceptions import ToolError

    from nz_openbank_mcp.safety import shown

    with pytest.raises(ToolError, match="Expected text, got int"):
        shown(5)  # type: ignore[arg-type]


def test_describe_request_lists_values_and_omits_empty() -> None:
    from nz_openbank_mcp.safety import describe_request

    text = describe_request(
        "Do it:",
        [("a", "one"), ("b", None), ("c", ""), ("d", []), ("e", ["x", "y"])],
    )
    assert text == 'Do it:\n- a: "one"\n- e: "x", "y"'
    assert "None" not in text


async def test_require_write_consent_builds_prompt_from_kwargs(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import describe_request, require_write_consent

    @require_write_consent(lambda kw: describe_request("Refresh:", [("account", kw["account_id"])]))
    async def my_tool(*, ctx: Any, account_id: str) -> str:
        return f"refreshed-{account_id}"

    ctx = ctx_factory(elicit_action="accept")
    result = await my_tool(ctx=ctx, account_id="acc_xyz")
    assert result == "refreshed-acc_xyz"
    assert ctx.elicit.await_args[0][0] == 'Confirm: Refresh:\n- account: "acc_xyz"'


async def test_prepare_runs_before_consent_and_its_values_reach_the_tool(
    writable_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import describe_request, require_write_consent

    order: list[str] = []

    async def prepare(_ctx: Any, kw: dict[str, Any]) -> None:
        order.append("prepare")
        kw["note"] = "filled"

    @require_write_consent(
        lambda kw: describe_request("Send:", [("note", kw["note"])]), prepare=prepare
    )
    async def my_tool(*, ctx: Any, note: str | None = None) -> str | None:
        order.append("tool")
        return note

    ctx = ctx_factory(elicit_action="accept")
    assert await my_tool(ctx=ctx) == "filled"
    assert order == ["prepare", "tool"]
    assert ctx.elicit.await_args[0][0] == 'Confirm: Send:\n- note: "filled"'


async def test_prepare_does_not_run_when_read_only(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ReadOnlyError, require_write_consent

    async def prepare(_ctx: Any, _kw: dict[str, Any]) -> None:
        raise AssertionError("prepare must not run")

    @require_write_consent("Send.", prepare=prepare)
    async def my_tool(*, ctx: Any) -> None:
        return None

    ctx = ctx_factory()
    with pytest.raises(ReadOnlyError):
        await my_tool(ctx=ctx)
    ctx.elicit.assert_not_awaited()


async def test_elicit_value_returns_data_on_accept(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import elicit_value

    ctx = ctx_factory(elicit_action="accept", elicit_data="txn_002")
    value = await elicit_value(ctx, "Provide id:", str)
    assert value == "txn_002"
    assert ctx.elicit.await_args.kwargs["response_type"] is str


async def test_elicit_value_raises_on_decline(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationDeclinedError, elicit_value

    ctx = ctx_factory(elicit_action="decline")
    with pytest.raises(ElicitationDeclinedError):
        await elicit_value(ctx, "Provide id:", str)


async def test_elicit_value_raises_on_cancel(
    fake_env: None, ctx_factory: Callable[..., MagicMock]
) -> None:
    from nz_openbank_mcp.safety import ElicitationCancelledError, elicit_value

    ctx = ctx_factory(elicit_action="cancel")
    with pytest.raises(ElicitationCancelledError):
        await elicit_value(ctx, "Provide id:", str)
