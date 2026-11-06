"""Transactions sub-server: 5 read tools + 1 write tool."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from pydantic import BeforeValidator, Field

from nz_openbank_mcp import deps
from nz_openbank_mcp.aio import pair
from nz_openbank_mcp.client import AkahuClient, TransactionPages, check_akahu_id
from nz_openbank_mcp.formatting import (
    akahu_bound,
    format_money,
    local_date,
    money_number,
    nz_day,
    nz_today,
    to_decimal,
)
from nz_openbank_mcp.models import Account, PendingTransaction, Transaction
from nz_openbank_mcp.safety import (
    MAX_SHOWN_CHARS,
    ElicitationDeclinedError,
    describe_request,
    elicit_value,
    require_write_consent,
)
from nz_openbank_mcp.tool_metadata import (
    OPEN_WORLD_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
)

# Mount namespace; exposed tool names are `txn_<function>`.
NAMESPACE = "txn"
server: FastMCP[Any] = FastMCP("transactions")

IssueType = Literal["DUPLICATE", "ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION"]


def _integral(value: object) -> object:
    # Some MCP hosts send JSON whole numbers as floats (100.0).
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


Limit = Annotated[int, Field(ge=1, le=500, strict=True), BeforeValidator(_integral)]

AmountBound = Annotated[float, Field(allow_inf_nan=False)]

SEARCH_DEFAULT_DAYS = 90


def currency_map(accounts: list[Account]) -> dict[str, str]:
    """account_id -> ISO currency, for accounts that report one."""
    return {a.id: a.balance.currency for a in accounts if a.balance and a.balance.currency}


async def _currencies(client: AkahuClient) -> dict[str, str]:
    return currency_map(await client.list_accounts())


async def _scan(
    client: AkahuClient,
    pages: TransactionPages,
    keep: Callable[[Transaction], bool],
    limit: int,
) -> dict[str, Any]:
    """Collect up to `limit` kept transactions while the currency lookup runs alongside."""

    async def collect() -> list[Transaction]:
        found: list[Transaction] = []
        async for txn in pages:
            if keep(txn):
                found.append(txn)
                if len(found) >= limit:
                    break
        return found

    collected, currencies = await pair(collect(), _currencies(client))
    return {
        "transactions": [_summarise(t, currencies) for t in collected],
        "truncated": pages.truncated,
        # Conservative: true whenever the result is full, as more may exist.
        "limit_reached": len(collected) >= limit,
    }


def _summarise(txn: Transaction, currencies: dict[str, str]) -> dict[str, Any]:
    """Settled transaction in the LLM-facing shape, in its account's currency."""
    currency = currencies.get(txn.account)
    return {
        "id": txn.id,
        "account_id": txn.account,
        "date": local_date(txn.date),
        "description": txn.description,
        "amount": format_money(txn.amount, currency),
        "amount_raw": money_number(txn.amount),
        "currency": currency,
        "type": txn.type,
        "merchant": txn.merchant.name if txn.merchant else None,
        "category": txn.category.name if txn.category else None,
    }


def summarise_pending(txn: PendingTransaction, currency: str | None) -> dict[str, Any]:
    """Pending transaction in the LLM-facing shape. Pending items have no id."""
    return {
        "account_id": txn.account,
        "date": local_date(txn.date),
        "description": txn.description,
        "amount": format_money(txn.amount, currency),
        "amount_raw": money_number(txn.amount),
        "currency": currency,
        "type": txn.type,
        "merchant": txn.merchant.name if txn.merchant else None,
        "category": txn.category.name if txn.category else None,
        "pending": True,
    }


@server.tool(title="Get Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def get_transactions(
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    min_amount: AmountBound | None = None,
    max_amount: AmountBound | None = None,
    limit: Limit = 100,
) -> dict[str, Any]:
    """List settled transactions with optional filters.

    Returns {"transactions": [...], "truncated": bool, "limit_reached": bool}
    where each entry has id, account_id, date (YYYY-MM-DD, NZ calendar day),
    description, amount (formatted in the account's currency, e.g. "-$12.50"
    or "-USD 9.99"), amount_raw (number rounded to cents; negative = debit),
    currency (ISO code, or None when the account's currency is unknown, in
    which case amount has no symbol, e.g. "-1,234.50"), type, merchant
    (str | None), category (str | None). The list is complete only when both
    flags are false. limit_reached is true when the result holds `limit`
    items, so more may exist: raise limit (up to 500) or narrow the dates
    before totalling. truncated is true when the scan stopped at the 20-page
    cap before reaching the end of the range; narrow the dates and call again.

    Args:
        account_id: Scope to one account (sent to Akahu).
        start_date: Earliest NZ day as YYYY-MM-DD (inclusive), or an ISO 8601
            timestamp passed to Akahu as an exclusive lower bound (UTC if it
            has no offset).
        end_date: Latest NZ day as YYYY-MM-DD (inclusive), or an ISO 8601
            timestamp passed to Akahu as an inclusive upper bound (UTC if it
            has no offset).
        category: Exact category name (applied after fetching).
        min_amount: Lower bound on signed amount (applied after fetching; negatives are debits).
        max_amount: Upper bound on signed amount (applied after fetching).
        limit: Max items returned, 1 to 500 (default 100).
    """
    start = akahu_bound(start_date, end=False)
    end = akahu_bound(end_date, end=True)
    client = deps.get_client()
    if account_id is not None:
        pages = client.iter_account_transactions(account_id, start=start, end=end)
    else:
        pages = client.iter_transactions(start=start, end=end)

    low = None if min_amount is None else to_decimal(min_amount)
    high = None if max_amount is None else to_decimal(max_amount)

    def keep(txn: Transaction) -> bool:
        if category and (txn.category is None or txn.category.name != category):
            return False
        if low is not None and txn.amount < low:
            return False
        return high is None or txn.amount <= high

    return await _scan(client, pages, keep, limit)


@server.tool(title="Get Transaction", annotations=READ_ONLY_ANNOTATIONS)
async def get_transaction(transaction_id: str) -> dict[str, Any]:
    """Fetch one settled transaction by id.

    Returns the same shape as one entry in get_transactions["transactions"].

    Args:
        transaction_id: Akahu transaction id (e.g. "txn_a1b2c3").
    """
    client = deps.get_client()
    txn, currencies = await pair(client.get_transaction(transaction_id), _currencies(client))
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
    txns, currencies = await pair(client.get_transactions_by_ids(ids), _currencies(client))
    return {"transactions": [_summarise(t, currencies) for t in txns]}


@server.tool(title="Get Pending Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def get_pending_transactions() -> dict[str, Any]:
    """List all pending (not-yet-settled) transactions across the user's accounts.

    Pending transactions affect available balance immediately but do not
    appear in get_transactions until they settle, and they can change or
    vanish before then. Returns {"transactions": [...]} where each entry has
    account_id, date (YYYY-MM-DD, NZ calendar day), description, amount
    (formatted in the account's currency), amount_raw, currency (None if
    unknown), type, merchant, category and pending (always true). Pending
    entries have no id.
    """
    client = deps.get_client()
    txns, currencies = await pair(client.get_pending_transactions(), _currencies(client))
    return {"transactions": [summarise_pending(t, currencies.get(t.account)) for t in txns]}


@server.tool(title="Search Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def search_transactions(
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: Limit = 50,
) -> dict[str, Any]:
    """Case-insensitive substring search across description and merchant name.

    Searches settled transactions in a date window until `limit` matches are
    found. Without start_date the window is the 90 NZ days ending on end_date,
    or ending today. Use for free-text lookups; prefer get_transactions when
    filtering by account or amount. Returns {"transactions": [...],
    "truncated": bool, "limit_reached": bool} with the same shape and meaning
    as get_transactions: if limit_reached, more matches may exist, so raise
    limit (up to 500) or narrow the dates.

    Args:
        query: Substring to match (case-insensitive).
        start_date: Earliest NZ day as YYYY-MM-DD (inclusive) or an ISO 8601
            timestamp (UTC if it has no offset); defaults to 90 days back.
        end_date: Latest NZ day as YYYY-MM-DD (inclusive) or an ISO 8601
            timestamp (UTC if it has no offset); defaults to no upper bound.
        limit: Max matches returned, 1 to 500 (default 50).
    """
    end = akahu_bound(end_date, end=True)
    start = akahu_bound(start_date, end=False)
    if start is None:
        last_day = nz_day(end_date or "") if end else nz_today()
        first_day = last_day - timedelta(days=SEARCH_DEFAULT_DAYS - 1)
        start = akahu_bound(first_day.isoformat(), end=False)
    client = deps.get_client()
    needle = query.lower()

    def keep(txn: Transaction) -> bool:
        haystack = txn.description.lower()
        if txn.merchant:
            haystack += " " + txn.merchant.name.lower()
        return needle in haystack

    return await _scan(client, client.iter_transactions(start=start, end=end), keep, limit)


async def _complete_issue(ctx: Any, kw: dict[str, Any]) -> None:
    check_akahu_id(kw.get("transaction_id") or "", name="transaction_id")
    issue_type = kw["issue_type"]
    if issue_type == "DUPLICATE" and not kw.get("other_transaction_id"):
        other = await elicit_value(ctx, "Provide the paired duplicate transaction id:", str)
        if not isinstance(other, str) or not other.strip():
            raise ElicitationDeclinedError("User provided no transaction id.")
        kw["other_transaction_id"] = other
    if kw.get("other_transaction_id"):
        check_akahu_id(kw["other_transaction_id"], name="other_transaction_id")
    if issue_type in {"ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION"} and not kw.get("fields"):
        fields = await elicit_value(
            ctx,
            f"List the affected field names for {issue_type} (e.g. merchant, category):",
            list[str],
        )
        if not fields:
            raise ElicitationDeclinedError("User provided no fields.")
        kw["fields"] = fields


def _describe_issue(kw: dict[str, Any]) -> str:
    return describe_request(
        "Send this support ticket to a person at Akahu:",
        [
            ("transaction", kw.get("transaction_id")),
            ("type", kw.get("issue_type")),
            ("duplicate of", kw.get("other_transaction_id")),
            ("fields", kw.get("fields")),
            ("comment", kw.get("comment")),
        ],
    )


@server.tool(
    title="Report Transaction Issue",
    annotations=OPEN_WORLD_WRITE_ANNOTATIONS,
)
@require_write_consent(
    _describe_issue, namespace=NAMESPACE, automatable=False, prepare=_complete_issue
)
async def report_transaction_issue(
    *,
    ctx: Context,
    transaction_id: str,
    issue_type: IssueType,
    fields: list[str] | None = None,
    comment: Annotated[str | None, Field(max_length=MAX_SHOWN_CHARS)] = None,
    other_transaction_id: str | None = None,
) -> dict[str, Any]:
    """Submit a support ticket about a transaction to Akahu staff.

    Sends a ticket to a human at Akahu support. Always elicits user
    confirmation (not bypass-eligible); the prompt shows every value in the
    ticket, including the comment. Pass every required value as an argument;
    older clients may ask the user for a missing one before that prompt.
    issue_type validation:
      - "DUPLICATE": requires other_transaction_id (the paired duplicate).
      - "ENRICHMENT_ERROR": requires fields=[...] listing affected field names.
      - "ENRICHMENT_SUGGESTION": requires fields=[...] listing suggested fields.

    Returns {"success": bool, "message": str | None}.

    Args:
        transaction_id: Akahu transaction id the ticket is about.
        issue_type: One of "DUPLICATE", "ENRICHMENT_ERROR", "ENRICHMENT_SUGGESTION".
        fields: Affected field names. Required for ENRICHMENT_* issue types;
            pass them here. Older clients may ask the user for them if omitted.
        comment: Optional free-text context for the support agent, up to
            1,000 characters.
        other_transaction_id: Paired transaction id. Required for DUPLICATE;
            pass it here. Older clients may ask the user for it if omitted.
    """
    result = await deps.get_client().report_transaction_issue(
        transaction_id,
        issue_type=issue_type,
        fields=fields,
        comment=comment,
        other_transaction_id=other_transaction_id,
    )
    return {"success": result.success, "message": result.message}
