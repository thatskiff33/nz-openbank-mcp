"""Tests for the transactions sub-server."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from nz_openbank_mcp.client import TransactionPages
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


def _async_iter(items: list[Transaction]) -> TransactionPages:
    async def one_page(_cursor: str | None) -> tuple[list[Transaction], str | None]:
        return items, None

    return TransactionPages(one_page)


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
    assert result["truncated"] is False


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
    assert result["transactions"][0]["amount"] == "-10.00"
    assert result["transactions"][0]["currency"] is None


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
    """A missing other_transaction_id is asked for first; the consent prompt then shows it."""
    from fastmcp.server.elicitation import AcceptedElicitation

    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data="txn_002"),
        AcceptedElicitation(data={}),
    ]
    result = await report_transaction_issue(
        ctx=ctx, transaction_id="txn_001", issue_type="DUPLICATE"
    )
    assert result["success"] is True
    assert ctx.elicit.await_count == 2
    _, kwargs = patched_client.report_transaction_issue.await_args
    assert kwargs["other_transaction_id"] == "txn_002"
    assert ctx.elicit.await_args_list[1][0][0] == (
        "Confirm: Send this support ticket to a person at Akahu:\n"
        '- transaction: "txn_001"\n'
        '- type: "DUPLICATE"\n'
        '- duplicate of: "txn_002"'
    )


async def test_report_transaction_issue_enrichment_elicits_fields(
    writable_env: None, ctx_factory: Callable[..., MagicMock], patched_client: MagicMock
) -> None:
    from fastmcp.server.elicitation import AcceptedElicitation

    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data=["merchant", "category"]),
        AcceptedElicitation(data={}),
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
        DeclinedElicitation(),
        AcceptedElicitation(data={}),
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
        CancelledElicitation(),
        AcceptedElicitation(data={}),
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
        AcceptedElicitation(data=[]),
        AcceptedElicitation(data={}),
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
            "merchant": None,
            "category": None,
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
            "merchant": None,
            "category": None,
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
    client.get_transactions_by_ids = AsyncMock(return_value=[usd])
    client.iter_account_transactions = MagicMock(
        side_effect=lambda _account_id, **_: _async_iter([usd])
    )
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
        get_transactions_by_ids,
        search_transactions,
    )

    listed = (await get_transactions())["transactions"][0]
    assert (listed["amount"], listed["currency"]) == ("-USD 9.99", "USD")
    assert (await search_transactions(query="saas"))["transactions"][0]["amount"] == "-USD 9.99"
    assert (await get_transaction(transaction_id="txn_usd"))["amount"] == "-USD 9.99"
    pending = (await get_pending_transactions())["transactions"][0]
    assert (pending["amount"], pending["currency"]) == ("-USD 5.50", "USD")
    by_ids = (await get_transactions_by_ids(ids=["txn_usd"]))["transactions"][0]
    assert by_ids["amount"] == "-USD 9.99"
    scoped = (await get_transactions(account_id="acc_usd_003"))["transactions"][0]
    assert scoped["amount"] == "-USD 9.99"


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
    # 90 NZ days, 2026-08-04 to 2026-11-01 inclusive.
    patched_client.iter_transactions.assert_called_once_with(
        start="2026-08-03T11:59:59.999Z", end=None
    )


@pytest.mark.parametrize("blank", ["", "   "])
async def test_search_blank_start_still_uses_default_window(
    fake_env: None, patched_client: MagicMock, monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    from datetime import date

    from nz_openbank_mcp.tools import transactions
    from nz_openbank_mcp.tools.transactions import search_transactions

    monkeypatch.setattr(transactions, "nz_today", lambda: date(2026, 11, 1))
    await search_transactions(query="x", start_date=blank, end_date=blank)
    patched_client.iter_transactions.assert_called_once_with(
        start="2026-08-03T11:59:59.999Z", end=None
    )


@pytest.mark.parametrize(
    "end_date", ["2025-12-31", "2025-12-31T05:00:00Z", "2025-12-31T10:00:00+13:00"]
)
async def test_search_window_ends_at_end_date(
    fake_env: None, patched_client: MagicMock, end_date: str
) -> None:
    from nz_openbank_mcp.formatting import akahu_bound
    from nz_openbank_mcp.tools.transactions import search_transactions

    await search_transactions(query="x", end_date=end_date)
    # 90 NZ days, 2025-10-03 to 2025-12-31 inclusive.
    patched_client.iter_transactions.assert_called_once_with(
        start="2025-10-02T10:59:59.999Z", end=akahu_bound(end_date, end=True)
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
        for bad in (0, 501, "5", True, 2.5):
            with pytest.raises(ToolError, match="limit"):
                await c.call_tool("txn_get_transactions", {"limit": bad})
    patched_client.iter_transactions.assert_not_called()


async def test_pending_keeps_enrichment_when_present(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp import deps
    from nz_openbank_mcp.tools.transactions import get_pending_transactions

    item = {
        **load_fixture("pending_transactions")["items"][0],
        "merchant": {"_id": "merchant_demo", "name": "Demo Cafe"},
        "category": {"_id": "cat_demo", "name": "Cafes"},
    }
    client = MagicMock()
    client.get_pending_transactions = AsyncMock(
        return_value=[PendingTransaction.model_validate(item)]
    )
    client.list_accounts = AsyncMock(return_value=_fake_accounts())
    monkeypatch.setattr(deps, "get_client", lambda: client)
    entry = (await get_pending_transactions())["transactions"][0]
    assert (entry["merchant"], entry["category"]) == ("Demo Cafe", "Cafes")


async def test_limit_accepts_whole_number_floats(fake_env: None, patched_client: MagicMock) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        result = await c.call_tool("txn_get_transactions", {"limit": 2.0})
    assert len(result.structured_content["transactions"]) == 2


async def test_bad_date_filter_fails_before_any_request(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await search_transactions(query="x", start_date="2026-01-01", end_date="yesterday")
    patched_client.iter_transactions.assert_not_called()
    patched_client.list_accounts.assert_not_called()


# ---------- page cap ----------


def _endless_pages(txn: Transaction) -> TransactionPages:
    async def page(_cursor: str | None) -> tuple[list[Transaction], str | None]:
        return [txn], "more"

    return TransactionPages(page)


async def test_get_transactions_reports_truncation_at_page_cap(
    fake_env: None, patched_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nz_openbank_mcp.client as client_mod
    from nz_openbank_mcp.tools.transactions import get_transactions

    monkeypatch.setattr(client_mod, "MAX_PAGES", 2)
    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _endless_pages(_txn()))
    result = await get_transactions(category="none-match")
    assert result == {"transactions": [], "truncated": True, "limit_reached": False}


async def test_search_reports_truncation_at_page_cap(
    fake_env: None, patched_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nz_openbank_mcp.client as client_mod
    from nz_openbank_mcp.tools.transactions import search_transactions

    monkeypatch.setattr(client_mod, "MAX_PAGES", 2)
    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _endless_pages(_txn()))
    result = await search_transactions(query="foo", limit=10)
    assert len(result["transactions"]) == 2
    assert result["truncated"] is True


async def test_search_reaching_limit_reports_limit_reached_not_truncated(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _endless_pages(_txn()))
    result = await search_transactions(query="foo", limit=3)
    assert len(result["transactions"]) == 3
    assert result["truncated"] is False
    assert result["limit_reached"] is True


# ---------- limit_reached (COR-01) ----------


def _one_page_of(count: int) -> TransactionPages:
    txns = [_txn(_id=f"txn_{i}") for i in range(count)]
    return _async_iter(txns)


async def test_get_transactions_flags_a_limit_cut_off(
    fake_env: None, patched_client: MagicMock
) -> None:
    """150 transactions in range with limit 100: the result must say it is incomplete."""
    from nz_openbank_mcp.tools.transactions import get_transactions

    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _one_page_of(150))
    result = await get_transactions(start_date="2026-10-01", end_date="2026-10-31")
    assert len(result["transactions"]) == 100
    assert result["truncated"] is False
    assert result["limit_reached"] is True


async def test_get_transactions_within_limit_is_not_flagged(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _one_page_of(99))
    result = await get_transactions()
    assert len(result["transactions"]) == 99
    assert result["truncated"] is False
    assert result["limit_reached"] is False


async def test_search_within_limit_is_not_flagged(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import search_transactions

    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _one_page_of(5))
    result = await search_transactions(query="foo", limit=50)
    assert len(result["transactions"]) == 5
    assert result["limit_reached"] is False


async def test_page_cap_is_truncated_without_limit_reached(
    fake_env: None, patched_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nz_openbank_mcp.client as client_mod
    from nz_openbank_mcp.tools.transactions import get_transactions

    monkeypatch.setattr(client_mod, "MAX_PAGES", 2)
    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _endless_pages(_txn()))
    result = await get_transactions(limit=10)
    assert result["truncated"] is True
    assert result["limit_reached"] is False


async def test_tool_descriptions_explain_limit_reached(fake_env: None) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        tools = {t.name: t for t in await c.list_tools()}
    for name in ("txn_get_transactions", "txn_search_transactions"):
        assert "limit_reached" in (tools[name].description or "")


# ---------- currency lookup runs alongside the scan (PERF-01) ----------


@pytest.mark.parametrize("tool", ["get_transactions", "search_transactions"])
async def test_accounts_lookup_does_not_delay_the_first_page(
    fake_env: None, patched_client: MagicMock, tool: str
) -> None:
    """/accounts only answers once a page was requested; a serial lookup would hang."""
    import asyncio

    from nz_openbank_mcp.tools import transactions

    page_requested = asyncio.Event()

    async def page(_cursor: str | None) -> tuple[list[Transaction], str | None]:
        page_requested.set()
        return [_txn(description="foo")], None

    async def slow_accounts() -> list[Account]:
        await page_requested.wait()
        return _fake_accounts()

    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: TransactionPages(page))
    patched_client.list_accounts = slow_accounts
    call = getattr(transactions, tool)
    kwargs = {"query": "foo"} if tool == "search_transactions" else {}
    async with asyncio.timeout(2):
        result = await call(**kwargs)
    assert result["transactions"][0]["currency"] == "NZD"


async def test_transactions_on_account_without_balance_currency_have_no_currency(
    fake_env: None, patched_client: MagicMock
) -> None:
    """COR-02: an account whose balance has no currency gives currency None, not NZD."""
    from nz_openbank_mcp.tools.transactions import get_transactions

    item = load_fixture("accounts")["items"][0]
    no_currency = Account.model_validate({**item, "balance": {"current": 1.0}})
    patched_client.list_accounts = AsyncMock(return_value=[no_currency])
    patched_client.iter_transactions = MagicMock(
        side_effect=lambda **_: _async_iter([_txn(_account=no_currency.id, amount=-1234.5)])
    )
    t0 = (await get_transactions())["transactions"][0]
    assert t0["currency"] is None
    assert t0["amount"] == "-1,234.50"


async def test_accounts_lookup_failure_is_raised_as_itself(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    patched_client.list_accounts = AsyncMock(side_effect=ToolError("accounts down"))
    with pytest.raises(ToolError, match="accounts down"):
        await get_transactions()


async def test_amount_filters_and_amount_raw_use_cents(
    fake_env: None, patched_client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import get_transactions

    txns = [_txn(_id="a", amount=-10.005), _txn(_id="b", amount=-10.01)]
    patched_client.iter_transactions = MagicMock(side_effect=lambda **_: _async_iter(txns))
    result = await get_transactions(min_amount=-10.005)
    assert [t["id"] for t in result["transactions"]] == ["a"]
    assert result["transactions"][0]["amount_raw"] == -10.0
    assert result["transactions"][0]["amount"] == "-$10.00"


@pytest.mark.parametrize("bound", ["NaN", "Infinity", "-Infinity"])
async def test_non_finite_amount_filters_are_rejected(fake_env: None, bound: str) -> None:
    from nz_openbank_mcp.server import build_server

    async with Client(build_server()) as c:
        with pytest.raises(ToolError, match="finite"):
            await c.call_tool("txn_get_transactions", {"min_amount": bound})
