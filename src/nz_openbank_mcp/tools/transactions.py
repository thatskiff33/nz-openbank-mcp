"""Transactions sub-server: 5 read tools + 1 write tool."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from nz_openbank_mcp import deps
from nz_openbank_mcp.client import AkahuClient
from nz_openbank_mcp.formatting import akahu_bound, format_money, local_date, nz_today
from nz_openbank_mcp.models import Account, PendingTransaction, Transaction
from nz_openbank_mcp.safety import (
    ElicitationDeclinedError,
    elicit_value,
    require_write_consent,
)
from nz_openbank_mcp.tool_metadata import (
    NON_DESTRUCTIVE_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
)

server: FastMCP[Any] = FastMCP("transactions")

IssueType = Literal["DUPLICATE", "ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION"]
Limit = Annotated[int, Field(ge=1, le=500)]

SEARCH_DEFAULT_DAYS = 90


def currency_map(accounts: list[Account]) -> dict[str, str]:
    """account_id -> ISO currency, for accounts that report one."""
    return {a.id: a.balance.currency for a in accounts if a.balance and a.balance.currency}


async def _currencies(client: AkahuClient) -> dict[str, str]:
    return currency_map(await client.list_accounts())


def _summarise(txn: Transaction, currencies: dict[str, str]) -> dict[str, Any]:
    """Settled transaction in the LLM-facing shape, in its account's currency."""
    currency = currencies.get(txn.account, "NZD")
    return {
        "id": txn.id,
        "account_id": txn.account,
        "date": local_date(txn.date),
        "description": txn.description,
        "amount": format_money(txn.amount, currency),
        "amount_raw": txn.amount,
        "currency": currency,
        "type": txn.type,
        "merchant": txn.merchant.name if txn.merchant else None,
        "category": txn.category.name if txn.category else None,
    }


def summarise_pending(txn: PendingTransaction, currency: str) -> dict[str, Any]:
    """Pending transaction in the LLM-facing shape. Pending items have no id."""
    return {
        "account_id": txn.account,
        "date": local_date(txn.date),
        "description": txn.description,
        "amount": format_money(txn.amount, currency),
        "amount_raw": txn.amount,
        "currency": currency,
        "type": txn.type,
        "pending": True,
    }


@server.tool(title="Get Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def get_transactions(
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: Limit = 100,
) -> dict[str, Any]:
    """List settled transactions with optional filters.

    Returns {"transactions": [...]} where each entry has id, account_id,
    date (YYYY-MM-DD, NZ calendar day), description, amount (formatted in the
    account's currency, e.g. "-$12.50" or "-USD 9.99"), amount_raw (float;
    negative = debit), currency (ISO code), type, merchant (str | None),
    category (str | None).

    Args:
        account_id: Scope to one account (sent to Akahu).
        start_date: Earliest NZ day as YYYY-MM-DD (inclusive), or an ISO 8601
            timestamp passed to Akahu as an exclusive lower bound.
        end_date: Latest NZ day as YYYY-MM-DD (inclusive), or an ISO 8601
            timestamp passed to Akahu as an inclusive upper bound.
        category: Exact category name (applied after fetching).
        min_amount: Lower bound on signed amount (applied after fetching; negatives are debits).
        max_amount: Upper bound on signed amount (applied after fetching).
        limit: Max items returned, 1 to 500 (default 100).
    """
    client = deps.get_client()
    start = akahu_bound(start_date, end=False)
    end = akahu_bound(end_date, end=True)
    currencies = await _currencies(client)
    if account_id is not None:
        iterator = client.iter_account_transactions(account_id, start=start, end=end)
    else:
        iterator = client.iter_transactions(start=start, end=end)

    collected: list[Transaction] = []
    async for txn in iterator:
        if category and (txn.category is None or txn.category.name != category):
            continue
        if min_amount is not None and txn.amount < min_amount:
            continue
        if max_amount is not None and txn.amount > max_amount:
            continue
        collected.append(txn)
        if len(collected) >= limit:
            break
    return {"transactions": [_summarise(t, currencies) for t in collected]}


@server.tool(title="Get Transaction", annotations=READ_ONLY_ANNOTATIONS)
async def get_transaction(transaction_id: str) -> dict[str, Any]:
    """Fetch one settled transaction by id.

    Returns the same shape as one entry in get_transactions["transactions"].

    Args:
        transaction_id: Akahu transaction id (e.g. "txn_a1b2c3").
    """
    client = deps.get_client()
    txn, currencies = await asyncio.gather(
        client.get_transaction(transaction_id), _currencies(client)
    )
    return _summarise(txn, currencies)


@server.tool(title="Get Transactions By IDs", annotations=READ_ONLY_ANNOTATIONS)
async def get_transactions_by_ids(ids: list[str]) -> dict[str, Any]:
    """Batch-fetch settled transactions by their ids in one request.

    Useful when you have a list of transaction ids (e.g. from a prior query)
    and want to inspect them together. Returns {"transactions": [...]} with
    the same per-entry shape as get_transactions.

    Args:
        ids: List of Akahu transaction ids.
    """
    client = deps.get_client()
    txns, currencies = await asyncio.gather(
        client.get_transactions_by_ids(ids), _currencies(client)
    )
    return {"transactions": [_summarise(t, currencies) for t in txns]}


@server.tool(title="Get Pending Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def get_pending_transactions() -> dict[str, Any]:
    """List all pending (not-yet-settled) transactions across the user's accounts.

    Pending transactions affect available balance immediately but do not
    appear in get_transactions until they settle, and they can change or
    vanish before then. Returns {"transactions": [...]} where each entry has
    account_id, date (YYYY-MM-DD, NZ calendar day), description, amount
    (formatted in the account's currency), amount_raw, currency, type and
    pending (always true). Pending entries have no id.
    """
    client = deps.get_client()
    txns, currencies = await asyncio.gather(client.get_pending_transactions(), _currencies(client))
    return {"transactions": [summarise_pending(t, currencies.get(t.account, "NZD")) for t in txns]}


@server.tool(title="Search Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def search_transactions(
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: Limit = 50,
) -> dict[str, Any]:
    """Case-insensitive substring search across description and merchant name.

    Searches settled transactions in a date window, the last 90 days unless
    start_date is given, until `limit` matches are found. Use for free-text
    lookups; prefer get_transactions when filtering by account or amount.
    Returns {"transactions": [...]} with the same per-entry shape as
    get_transactions.

    Args:
        query: Substring to match (case-insensitive).
        start_date: Earliest NZ day as YYYY-MM-DD (inclusive) or an ISO 8601
            timestamp; defaults to 90 days before today (NZ).
        end_date: Latest NZ day as YYYY-MM-DD (inclusive) or an ISO 8601
            timestamp; defaults to no upper bound.
        limit: Max matches returned, 1 to 500 (default 50).
    """
    if start_date is None:
        start_date = (nz_today() - timedelta(days=SEARCH_DEFAULT_DAYS)).isoformat()
    client = deps.get_client()
    currencies = await _currencies(client)
    needle = query.lower()
    matches: list[Transaction] = []
    iterator = client.iter_transactions(
        start=akahu_bound(start_date, end=False), end=akahu_bound(end_date, end=True)
    )
    async for txn in iterator:
        haystack = txn.description.lower()
        if txn.merchant:
            haystack += " " + txn.merchant.name.lower()
        if needle in haystack:
            matches.append(txn)
            if len(matches) >= limit:
                break
    return {"transactions": [_summarise(t, currencies) for t in matches]}


@server.tool(
    title="Report Transaction Issue",
    annotations=NON_DESTRUCTIVE_WRITE_ANNOTATIONS,
)
@require_write_consent(
    "Report an issue with transaction {transaction_id} to Akahu support staff. "
    "Issue type: {issue_type}.",
    automatable=False,
)
async def report_transaction_issue(
    *,
    ctx: Context,
    transaction_id: str,
    issue_type: IssueType,
    fields: list[str] | None = None,
    comment: str | None = None,
    other_transaction_id: str | None = None,
) -> dict[str, Any]:
    """Submit a support ticket about a transaction to Akahu staff.

    Sends a ticket to a human at Akahu support. Always elicits user
    confirmation (not bypass-eligible). issue_type validation:
      - "DUPLICATE": requires other_transaction_id (the paired duplicate).
      - "ENRICHMENT_ERROR": requires fields=[...] listing affected field names.
      - "ENRICHMENT_SUGGESTION": requires fields=[...] listing suggested fields.

    Returns {"success": bool, "message": str | None}.

    Args:
        transaction_id: Akahu transaction id the ticket is about.
        issue_type: One of "DUPLICATE", "ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION".
        fields: Affected field names; required for ENRICHMENT_* issue types.
            Omitted -> the user is prompted to supply them via elicitation.
        comment: Optional free-text context for the support agent.
        other_transaction_id: Paired transaction id; required for DUPLICATE.
            Omitted -> the user is prompted to supply it via elicitation.
    """
    if issue_type == "DUPLICATE" and not other_transaction_id:
        other_transaction_id = await elicit_value(
            ctx,
            "Provide the paired duplicate transaction id:",
            str,
        )
    if issue_type in {"ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION"} and not fields:
        fields = await elicit_value(
            ctx,
            f"List the affected field names for {issue_type} (e.g. merchant, category):",
            list[str],
        )
        if not fields:
            raise ElicitationDeclinedError("User provided no fields.")

    result = await deps.get_client().report_transaction_issue(
        transaction_id,
        issue_type=issue_type,
        fields=fields,
        comment=comment,
        other_transaction_id=other_transaction_id,
    )
    return {"success": result.success, "message": result.message}
