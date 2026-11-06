"""Akahu ids are checked before they reach a URL path or a consent prompt."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tests.conftest import load_fixture

BAD_IDS = [
    ".",
    "..",
    "...",
    "",
    " ",
    "\t",
    "acc 1",
    "acc\n1",
    "acc\u200b1",
    "acc\u034f1",
    "%2e",
    "%2e%2e",
    "a/b",
    "../x",
    "..\\x",
    "\uff0e\uff0e",
    "\u2024\u2024",
    "acc.1",
    "x" * 129,
]
# Refused at every tool that takes an id, before any request or prompt.
TOOL_BAD_IDS = [".", "..", " ", "%2e", "a/b", "../x", "..\\x", "\uff0e\uff0e"]


@pytest_asyncio.fixture
async def real_client(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Tools use a real AkahuClient, so httpx path handling is exercised."""
    from nz_openbank_mcp import deps

    monkeypatch.setattr(deps, "_client", None)
    yield
    await deps.aclose_client()


@pytest.fixture
def akahu(respx_mock: respx.MockRouter) -> respx.MockRouter:
    """Answer /accounts (the currency lookup); record every other request."""
    respx_mock.get("/accounts").mock(
        return_value=httpx.Response(200, json=load_fixture("accounts"))
    )
    respx_mock.route().mock(return_value=httpx.Response(200, json={"success": True, "items": []}))
    return respx_mock


def _paths_other_than_accounts(router: respx.MockRouter) -> list[str]:
    return [c.request.url.path for c in router.calls if c.request.url.path != "/v1/accounts"]


# ---------- the shared check ----------


@pytest.mark.parametrize("bad", BAD_IDS)
def test_check_akahu_id_refuses(bad: str) -> None:
    from nz_openbank_mcp.client import check_akahu_id

    with pytest.raises(ToolError, match="account_id"):
        check_akahu_id(bad, name="account_id")


@pytest.mark.parametrize("good", ["acc_chq_001", "trans_abc-123", "user_1", "x" * 128])
def test_check_akahu_id_accepts(good: str) -> None:
    from nz_openbank_mcp.client import check_akahu_id

    assert check_akahu_id(good, name="account_id") == good


# ---------- read tools: refused before any request to the id's endpoint ----------


READ_CALLS = [
    ("acct_get_account", "account_id", {}),
    ("acct_get_account_balance", "account_id", {}),
    ("acct_get_pending_transactions", "account_id", {}),
    ("txn_get_transactions", "account_id", {}),
    ("txn_get_transaction", "transaction_id", {}),
]


@pytest.mark.parametrize(("tool", "param", "extra"), READ_CALLS)
@pytest.mark.parametrize("bad", TOOL_BAD_IDS)
async def test_read_tools_refuse_bad_ids(
    real_client: None,
    akahu: respx.MockRouter,
    tool: str,
    param: str,
    extra: dict[str, Any],
    bad: str,
) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        result = await c.call_tool(tool, {param: bad, **extra}, raise_on_error=False)
    assert result.is_error
    assert param in result.content[0].text  # type: ignore[union-attr]
    assert _paths_other_than_accounts(akahu) == []


async def test_get_transactions_by_ids_refuses_a_bad_id(
    real_client: None, akahu: respx.MockRouter
) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        result = await c.call_tool(
            "txn_get_transactions_by_ids", {"ids": ["txn_001", " "]}, raise_on_error=False
        )
    assert result.is_error
    assert _paths_other_than_accounts(akahu) == []


async def test_good_ids_still_reach_akahu(real_client: None, akahu: respx.MockRouter) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        await c.call_tool("txn_get_transactions", {"account_id": "acc_chq_001"})
    assert _paths_other_than_accounts(akahu) == ["/v1/accounts/acc_chq_001/transactions"]


# ---------- write tools: refused before the consent prompt and before any request ----------


@pytest.mark.parametrize("bad", [*TOOL_BAD_IDS, "acc\u200b1"])
async def test_refresh_account_refuses_before_consent(
    writable_env: None,
    real_client: None,
    akahu: respx.MockRouter,
    ctx_factory: Callable[..., MagicMock],
    bad: str,
) -> None:
    from nz_openbank_mcp.tools.accounts import refresh_account

    ctx = ctx_factory(elicit_action="accept")
    with pytest.raises(ToolError, match="account_id"):
        await refresh_account(ctx=ctx, account_id=bad)
    ctx.elicit.assert_not_awaited()
    assert akahu.calls.call_count == 0


@pytest.mark.parametrize("bad", TOOL_BAD_IDS)
async def test_refresh_account_refuses_under_bypass(
    bypass_env: None,
    real_client: None,
    akahu: respx.MockRouter,
    ctx_factory: Callable[..., MagicMock],
    bad: str,
) -> None:
    """With the bypass on there is no prompt, so the id check is the only guard."""
    from nz_openbank_mcp.tools.accounts import refresh_account

    with pytest.raises(ToolError, match="account_id"):
        await refresh_account(ctx=ctx_factory(), account_id=bad)
    assert akahu.calls.call_count == 0


@pytest.mark.parametrize("bad", TOOL_BAD_IDS)
async def test_verify_name_refuses_bad_account_id_before_consent(
    writable_env: None,
    real_client: None,
    akahu: respx.MockRouter,
    ctx_factory: Callable[..., MagicMock],
    bad: str,
) -> None:
    from nz_openbank_mcp.tools.identity import verify_name

    ctx = ctx_factory(elicit_action="accept")
    with pytest.raises(ToolError, match="account_id"):
        await verify_name(ctx=ctx, family_name="Example", account_id=bad)
    ctx.elicit.assert_not_awaited()
    assert akahu.calls.call_count == 0


@pytest.mark.parametrize("bad", TOOL_BAD_IDS)
@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("transaction_id", {"issue_type": "DUPLICATE", "other_transaction_id": "txn_002"}),
        ("other_transaction_id", {"transaction_id": "txn_001", "issue_type": "DUPLICATE"}),
    ],
)
async def test_report_issue_refuses_bad_ids_before_consent(
    writable_env: None,
    real_client: None,
    akahu: respx.MockRouter,
    ctx_factory: Callable[..., MagicMock],
    field: str,
    kwargs: dict[str, Any],
    bad: str,
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="accept")
    with pytest.raises(ToolError, match=field):
        await report_transaction_issue(ctx=ctx, **{field: bad}, **kwargs)
    ctx.elicit.assert_not_awaited()
    assert akahu.calls.call_count == 0


async def test_report_issue_refuses_a_bad_elicited_duplicate_id(
    writable_env: None,
    real_client: None,
    akahu: respx.MockRouter,
    ctx_factory: Callable[..., MagicMock],
) -> None:
    """An id the user types in at the prompt is checked like an argument."""
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="accept", elicit_data="..")
    with pytest.raises(ToolError, match="other_transaction_id"):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")
    assert ctx.elicit.await_count == 1  # the value prompt only, never the consent prompt
    assert akahu.calls.call_count == 0
