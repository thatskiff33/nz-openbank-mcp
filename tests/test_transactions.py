"""Tests for the transactions sub-server."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from nz_openbank_mcp.models import Account, PendingTransaction, SupportRequest, Transaction
from tests.conftest import load_fixture


def _fake_txns() -> list[Transaction]:
    return [Transaction.model_validate(i) for i in load_fixture("transactions")["items"]]


def _fake_accounts() -> list[Account]:
    return [Account.model_validate(i) for i in load_fixture("accounts")["items"]]


def _fake_pending() -> list[PendingTransaction]:
    items = load_fixture("pending_transactions")["items"]
    return [PendingTransaction.model_validate(i) for i in items]


def _usd_account() -> Account:
    return Account.model_validate(
        {
            **load_fixture("accounts")["items"][0],
            "_id": "acc_usd_003",
            "balance": {"currency": "USD", "current": 100.0},
        }
    )


def _txn(**overrides: object) -> Transaction:
    return Transaction.model_validate(
        {
            "_id": "txn_x",
            "_account": "acc_chq_001",
            "date": "2026-01-01T00:00:00Z",
            "description": "FOO",
            "amount": -10.00,
            "type": "EFTPOS",
            **overrides,
        }
    )


def _async_iter(items: list[Transaction]) -> AsyncIterator[Transaction]:
    async def gen() -> AsyncIterator[Transaction]:
        for t in items:
            yield t

    return gen()


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    from nz_openbank_mcp import deps

    client = MagicMock()
    txns = _fake_txns()
    client.iter_transactions = MagicMock(side_effect=lambda **_: _async_iter(txns))
    # iter_account_transactions mirrors iter_transactions but takes a positional
    # account_id. The fake just returns the same fixture - any per-account
    # filtering would be Akahu's job; the tool no longer filters client-side.
    client.iter_account_transactions = MagicMock(
        side_effect=lambda _account_id, **_: _async_iter(txns)
    )
    client.get_transaction = AsyncMock(return_value=txns[0])
    client.list_accounts = AsyncMock(return_value=_fake_accounts())
    client.report_transaction_issue = AsyncMock(return_value=SupportRequest(success=True))
    monkeypatch.setattr(deps, "get_client", lambda: client)
    return client


# ---------- get_transactions ----------


async def test_get_transactions_returns_all(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions()
    assert len(result["transactions"]) == 3
    t0 = result["transactions"][0]
    assert t0["id"] == "txn_001"
    assert t0["amount"] == "-$82.45"
    assert t0["merchant"] == "Demo Grocer"
    assert t0["category"] == "Groceries"


async def test_get_transactions_filters_by_amount(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions(min_amount=0)  # only positive (income)
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["id"] == "txn_003"


async def test_get_transactions_filters_max_amount(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions(max_amount=-89)  # only smaller-than-90 debits
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["id"] == "txn_002"


async def test_get_transactions_filters_by_category(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions(category="Groceries")
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["category"] == "Groceries"


async def test_get_transactions_with_account_id_routes_to_per_account_endpoint(
    fake_env: None, patched_client: MagicMock
) -> None:
    """When account_id is given, the tool must use iter_account_transactions
    (i.e. hit GET /accounts/{id}/transactions for server-side filtering) instead
    of pulling all txns and filtering client-side."""
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions(
        account_id="acc_chq_001",
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-31T23:59:59Z",
    )
    assert len(result["transactions"]) == 3  # the fixture returns 3 unfiltered
    patched_client.iter_account_transactions.assert_called_once()
    args, kwargs = patched_client.iter_account_transactions.call_args
    assert args[0] == "acc_chq_001"
    assert kwargs == {"start": "2026-05-01T00:00:00Z", "end": "2026-05-31T23:59:59Z"}
    # And the unfiltered iterator must NOT have been used.
    patched_client.iter_transactions.assert_not_called()


async def test_get_transactions_without_account_id_uses_all_txn_endpoint(
    fake_env: None, patched_client: MagicMock
) -> None:
    """When account_id is None, fall through to GET /transactions across all accounts."""
    from nz_openbank_mcp.tools.transactions import get_transactions

    await get_transactions(start_date="2026-05-01T00:00:00Z")
    patched_client.iter_transactions.assert_called_once_with(start="2026-05-01T00:00:00Z", end=None)
    patched_client.iter_account_transactions.assert_not_called()


async def test_get_transactions_respects_limit(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    result = await get_transactions(limit=2)
    assert len(result["transactions"]) == 2


async def test_get_transactions_handles_no_merchant_or_category(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_transactions

    plain = Transaction.model_validate(
        {
            "_id": "txn_x",
            "_account": "acc",
            "date": "2026-01-01T00:00:00Z",
            "description": "FOO",
            "amount": -10.00,
            "type": "EFTPOS",
        }
    )
    client = MagicMock()
    client.iter_transactions = MagicMock(side_effect=lambda **_: _async_iter([plain]))
    client.list_accounts = AsyncMock(return_value=[])
    monkeypatch.setattr(deps, "get_client", lambda: client)
    result = await get_transactions()
    assert result["transactions"][0]["merchant"] is None
    assert result["transactions"][0]["category"] is None
    assert result["transactions"][0]["amount"] == "-$10.00"
    assert result["transactions"][0]["currency"] == "NZD"


# ---------- get_transaction ----------


async def test_get_transaction_single(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import get_transaction

    result = await get_transaction(transaction_id="txn_001")
    assert result["id"] == "txn_001"
    assert result["amount"] == "-$82.45"


# ---------- search_transactions ----------


async def test_search_transactions_by_description(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    result = await search_transactions(query="utility")  # case-insensitive
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["id"] == "txn_002"


async def test_search_transactions_by_merchant(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    result = await search_transactions(query="grocer")
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["merchant"] == "Demo Grocer"


async def test_search_transactions_no_match(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    result = await search_transactions(query="zzznever")
    assert result["transactions"] == []


async def test_search_transactions_respects_limit(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    result = await search_transactions(query="", limit=2)  # empty query matches all
    assert len(result["transactions"]) == 2


# ---------- report_transaction_issue (write, NOT bypass-eligible) ----------


async def test_report_transaction_issue_blocks_in_readonly(
    fake_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.safety import ReadOnlyError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    with pytest.raises(ReadOnlyError):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")


async def test_report_transaction_issue_accept(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="accept")
    result = await report_transaction_issue(
        ctx=ctx,
        transaction_id="txn_001",
        issue_type="DUPLICATE",
        other_transaction_id="txn_002",
    )
    assert result["success"] is True
    patched_client.report_transaction_issue.assert_awaited_once()


async def test_report_transaction_issue_decline(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.safety import ElicitationDeclinedError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="decline")
    with pytest.raises(ElicitationDeclinedError):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")


async def test_report_transaction_issue_cancel(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.safety import ElicitationCancelledError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="cancel")
    with pytest.raises(ElicitationCancelledError):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")


async def test_report_transaction_issue_still_elicits_under_bypass(
    bypass_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    """This tool is NOT marked automatable, so bypass must not skip elicit."""
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="accept")
    await report_transaction_issue(
        ctx=ctx,
        transaction_id="txn_001",
        issue_type="DUPLICATE",
        other_transaction_id="txn_002",
    )
    ctx.elicit.assert_awaited_once()


async def test_report_transaction_issue_rejects_unknown_issue_type(
    writable_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        with pytest.raises(ToolError, match="issue_type"):
            await c.call_tool(
                "txn_report_transaction_issue",
                {"transaction_id": "txn_001", "issue_type": "NOT_A_REAL_KIND"},
            )
    patched_client.report_transaction_issue.assert_not_called()


async def test_report_transaction_issue_duplicate_elicits_other_id(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    """When other_transaction_id is omitted, the tool prompts for it mid-call.

    Pattern: build ctx via ctx_factory(), then override ctx.elicit.side_effect
    with the sequence of results we want. First call is the safety
    confirmation (empty AcceptedElicitation), second is the typed value.
    """
    from fastmcp.server.elicitation import AcceptedElicitation

    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data={}),
        AcceptedElicitation(data="txn_002"),
    ]
    result = await report_transaction_issue(
        ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE"
    )
    assert result["success"] is True
    assert ctx.elicit.await_count == 2
    _, kwargs = patched_client.report_transaction_issue.await_args
    assert kwargs["other_transaction_id"] == "txn_002"


async def test_report_transaction_issue_enrichment_elicits_fields(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from fastmcp.server.elicitation import AcceptedElicitation

    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data={}),
        AcceptedElicitation(data=["merchant", "category"]),
    ]
    result = await report_transaction_issue(
        ctx=ctx, transaction_id="txn_001", issue_type="ENRICHMENT_ERROR"
    )
    assert result["success"] is True
    assert ctx.elicit.await_count == 2
    _, kwargs = patched_client.report_transaction_issue.await_args
    assert kwargs["fields"] == ["merchant", "category"]


async def test_report_transaction_issue_field_fill_decline(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

    from nz_openbank_mcp.safety import ElicitationDeclinedError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data={}),
        DeclinedElicitation(),
    ]
    with pytest.raises(ElicitationDeclinedError):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")
    patched_client.report_transaction_issue.assert_not_awaited()


async def test_report_transaction_issue_field_fill_cancel(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from fastmcp.server.elicitation import AcceptedElicitation, CancelledElicitation

    from nz_openbank_mcp.safety import ElicitationCancelledError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data={}),
        CancelledElicitation(),
    ]
    with pytest.raises(ElicitationCancelledError):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE")
    patched_client.report_transaction_issue.assert_not_awaited()


async def test_report_transaction_issue_empty_fields_treated_as_decline(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    """An empty list payload from the user is effectively a decline; do not
    forward an empty fields=[] body to Akahu (it would 400)."""
    from fastmcp.server.elicitation import AcceptedElicitation

    from nz_openbank_mcp.safety import ElicitationDeclinedError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data={}),
        AcceptedElicitation(data=[]),
    ]
    with pytest.raises(ElicitationDeclinedError):
        await report_transaction_issue(
            ctx=ctx, transaction_id="txn_001", issue_type="ENRICHMENT_ERROR"
        )
    patched_client.report_transaction_issue.assert_not_awaited()


async def test_report_transaction_issue_enrichment_suggestion_ok(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory(elicit_action="accept")
    result = await report_transaction_issue(
        ctx=ctx,
        transaction_id="txn_001",
        issue_type="ENRICHMENT_SUGGESTION",
        fields=["merchant"],
        comment="Should be 'Woolworths NZ' now",
    )
    assert result["success"] is True


# ---------- get_transactions_by_ids ----------


async def test_get_transactions_by_ids(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_transactions_by_ids

    client = MagicMock()
    client.get_transactions_by_ids = AsyncMock(return_value=_fake_txns())
    client.list_accounts = AsyncMock(return_value=_fake_accounts())
    monkeypatch.setattr(deps, "get_client", lambda: client)
    result = await get_transactions_by_ids(ids=["txn_001", "txn_002"])
    assert len(result["transactions"]) == 3
    client.get_transactions_by_ids.assert_awaited_once_with(["txn_001", "txn_002"])


# ---------- get_pending_transactions ----------


async def test_get_pending_transactions(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_pending_transactions

    client = MagicMock()
    client.get_pending_transactions = AsyncMock(return_value=_fake_pending())
    client.list_accounts = AsyncMock(return_value=_fake_accounts())
    monkeypatch.setattr(deps, "get_client", lambda: client)
    result = await get_pending_transactions()
    assert result["transactions"] == [
        {
            "account_id": "acc_chq_001",
            "date": "2026-10-22",
            "description": "PENDING - DEMO CAFE",
            "amount": "-$5.50",
            "amount_raw": -5.5,
            "currency": "NZD",
            "type": "CREDIT CARD",
            "pending": True,
        },
        {
            "account_id": "acc_sav_002",
            "date": "2026-10-18",
            "description": "PENDING - DEMO TRANSFER",
            "amount": "$20.00",
            "amount_raw": 20.0,
            "currency": "NZD",
            "type": "TRANSFER",
            "pending": True,
        },
    ]


async def test_get_pending_transactions_empty(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_pending_transactions

    client = MagicMock()
    client.get_pending_transactions = AsyncMock(return_value=[])
    client.list_accounts = AsyncMock(return_value=_fake_accounts())
    monkeypatch.setattr(deps, "get_client", lambda: client)
    result = await get_pending_transactions()
    assert result["transactions"] == []


async def test_server_registers_six_tools(fake_env: None) -> None:
    from nz_openbank_mcp.tools.transactions import server

    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_transactions",
        "get_transaction",
        "search_transactions",
        "report_transaction_issue",
        "get_transactions_by_ids",
        "get_pending_transactions",
    }


# ---------- currency, NZ dates and date bounds ----------


@pytest.fixture
def usd_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    from nz_openbank_mcp import deps

    usd = _txn(_id="txn_usd", _account="acc_usd_003", amount=-9.99, description="DEMO SAAS")
    client = MagicMock()
    client.list_accounts = AsyncMock(return_value=[*_fake_accounts(), _usd_account()])
    client.iter_transactions = MagicMock(side_effect=lambda **_: _async_iter([usd]))
    client.get_transaction = AsyncMock(return_value=usd)
    client.get_pending_transactions = AsyncMock(
        return_value=[
            PendingTransaction.model_validate(
                {**load_fixture("pending_transactions")["items"][0], "_account": "acc_usd_003"}
            )
        ]
    )
    monkeypatch.setattr(deps, "get_client", lambda: client)
    return client


async def test_foreign_currency_account_renders_in_its_currency(
    fake_env: None, usd_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import (
        get_pending_transactions,
        get_transaction,
        get_transactions,
        search_transactions,
    )

    listed = (await get_transactions())["transactions"][0]
    assert (listed["amount"], listed["currency"]) == ("-USD 9.99", "USD")
    assert (await search_transactions(query="saas"))["transactions"][0]["amount"] == "-USD 9.99"
    assert (await get_transaction(transaction_id="txn_usd"))["amount"] == "-USD 9.99"
    pending = (await get_pending_transactions())["transactions"][0]
    assert (pending["amount"], pending["currency"]) == ("-USD 5.50", "USD")


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-10-17T11:00:00Z", "2026-10-18"),  # NZDT midnight posting
        ("2026-06-17T12:00:00Z", "2026-06-18"),  # NZST midnight posting
        ("2026-10-17T22:07:40Z", "2026-10-18"),  # 11:07am NZDT
        ("2026-10-17T10:59:59Z", "2026-10-17"),  # 11:59pm NZDT
    ],
)
async def test_dates_are_nz_calendar_days(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, stamp: str, expected: str
) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_transaction

    client = MagicMock()
    client.get_transaction = AsyncMock(return_value=_txn(date=stamp))
    client.list_accounts = AsyncMock(return_value=[])
    monkeypatch.setattr(deps, "get_client", lambda: client)
    assert (await get_transaction(transaction_id="txn_x"))["date"] == expected


async def test_date_only_filters_are_nz_days(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    await get_transactions(start_date="2026-10-18", end_date="2026-10-18")
    patched_client.iter_transactions.assert_called_once_with(
        start="2026-10-17T10:59:59.999Z", end="2026-10-18T10:59:59.999Z"
    )


async def test_search_defaults_to_last_90_nz_days(
    fake_env: None, patched_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from nz_openbank_mcp.tools import transactions
    from nz_openbank_mcp.tools.transactions import search_transactions

    monkeypatch.setattr(transactions, "nz_today", lambda: date(2026, 11, 1))
    await search_transactions(query="x")
    patched_client.iter_transactions.assert_called_once_with(
        start="2026-08-02T11:59:59.999Z", end=None
    )


async def test_search_honours_explicit_window(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    await search_transactions(query="x", start_date="2020-01-01T00:00:00Z", end_date="2026-06-30")
    patched_client.iter_transactions.assert_called_once_with(
        start="2020-01-01T00:00:00Z", end="2026-06-30T11:59:59.999Z"
    )


async def test_limit_is_bounded_in_schema(fake_env: None) -> None:
    from nz_openbank_mcp.tools.transactions import server

    tools = {t.name: t for t in await server.list_tools()}
    for name in ("get_transactions", "search_transactions"):
        limit = tools[name].parameters["properties"]["limit"]
        assert (limit["minimum"], limit["maximum"]) == (1, 500)
    issue = tools["report_transaction_issue"].parameters["properties"]["issue_type"]
    assert issue["enum"] == ["DUPLICATE", "ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION"]


async def test_limit_out_of_range_is_rejected(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        for bad in (0, 501):
            with pytest.raises(ToolError, match="limit"):
                await c.call_tool("txn_get_transactions", {"limit": bad})
    patched_client.iter_transactions.assert_not_called()
