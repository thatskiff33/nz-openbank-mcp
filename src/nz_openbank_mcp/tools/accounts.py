"""Accounts sub-server: 4 read tools + 2 write tools."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from nz_openbank_mcp import deps
from nz_openbank_mcp.aio import pair
from nz_openbank_mcp.formatting import format_money, mask_account
from nz_openbank_mcp.models import Account
from nz_openbank_mcp.safety import describe_request, require_write_consent
from nz_openbank_mcp.tool_metadata import (
    IDEMPOTENT_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
)
from nz_openbank_mcp.tools.transactions import summarise_pending

server: FastMCP[Any] = FastMCP("accounts")


def _summarise_account(account: Account) -> dict[str, Any]:
    """Convert an Account model to the LLM-facing dict shape (masked, formatted)."""
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type,
        "status": account.status,
        "formatted_account": mask_account(account.formatted_account),
        "connection": account.connection.name if account.connection else None,
        "balance": format_money(account.balance.current, account.balance.currency)
        if account.balance
        else None,
        "currency": account.balance.currency if account.balance else None,
    }


@server.tool(title="List Accounts", annotations=READ_ONLY_ANNOTATIONS)
async def list_accounts() -> dict[str, Any]:
    """List every connected account with masked numbers and formatted balances.

    Returns {"accounts": [...]} where each entry has id, name, type
    (CHECKING/SAVINGS/CREDITCARD/FOREIGN/...), status, formatted_account
    (masked, e.g. "01-****-***4567-00"), connection (institution name, e.g.
    "ANZ"), balance (formatted with currency, e.g. "$2,543.21" or
    "USD 100.00") and currency (ISO 4217 code). balance and currency are None
    if the account has no balance block.
    """
    accounts = await deps.get_client().list_accounts()
    return {"accounts": [_summarise_account(a) for a in accounts]}


@server.tool(title="Get Account", annotations=READ_ONLY_ANNOTATIONS)
async def get_account(account_id: str) -> dict[str, Any]:
    """Fetch a single account by id.

    Returns the same shape as one entry in list_accounts["accounts"]:
    id, name, type, status, formatted_account (masked), connection,
    balance (formatted with currency), currency.

    Args:
        account_id: Akahu account id (e.g. "acc_chq_001").
    """
    account = await deps.get_client().get_account(account_id)
    return _summarise_account(account)


@server.tool(title="Get Account Pending Transactions", annotations=READ_ONLY_ANNOTATIONS)
async def get_pending_transactions(account_id: str) -> dict[str, Any]:
    """List pending (not-yet-settled) transactions for one account.

    Pending entries affect available balance immediately and can change or
    vanish before they settle. Returns {"account_id", "transactions": [...]}
    where each transaction has account_id, date (YYYY-MM-DD, NZ calendar day),
    description, amount (formatted in the account's currency, e.g. "-$5.50"),
    amount_raw (float; negative = debit), currency (None if the account
    reports none, in which case amount has no symbol), type, merchant,
    category and pending (always true). Pending entries have no id.

    Args:
        account_id: Akahu account id.
    """
    client = deps.get_client()
    account, txns = await pair(
        client.get_account(account_id), client.get_account_pending_transactions(account_id)
    )
    currency = account.balance.currency if account.balance and account.balance.currency else None
    return {
        "account_id": account_id,
        "transactions": [summarise_pending(t, currency) for t in txns],
    }


@server.tool(title="Get Account Balance", annotations=READ_ONLY_ANNOTATIONS)
async def get_account_balance(account_id: str) -> dict[str, Any]:
    """Return just the balance for an account. Cheaper than get_account.

    Returns {"id", "balance", "available", "currency"} where balance and
    available are currency-formatted strings (e.g. "$2,543.21" or "USD 100.00")
    and currency is the ISO 4217 code. All three are None if the account has
    no balance block; available alone is None if not reported.

    Args:
        account_id: Akahu account id.
    """
    account = await deps.get_client().get_account(account_id)
    if account.balance is None:
        return {"id": account.id, "balance": None, "available": None, "currency": None}
    return {
        "id": account.id,
        "balance": format_money(account.balance.current, account.balance.currency),
        "available": format_money(account.balance.available, account.balance.currency)
        if account.balance.available is not None
        else None,
        "currency": account.balance.currency,
    }


@server.tool(
    title="Refresh All Accounts",
    annotations=IDEMPOTENT_WRITE_ANNOTATIONS,
)
@require_write_consent(
    "Refresh data for all your connected accounts. This is rate-limited by your bank.",
    automatable=True,
)
async def refresh_all_accounts(*, ctx: Context) -> dict[str, Any]:
    """Trigger Akahu to fetch fresh data for every connected account.

    Rate-limited by your bank. Idempotent within rate-limit windows. Use
    before a query that needs the freshest balance or transaction data.
    Requires write consent unless AKAHU_AUTOMATION_BYPASS=true. Returns
    {"success": bool, "message": str | None}.
    """
    result = await deps.get_client().refresh_all()
    return {"success": result.success, "message": result.message}


@server.tool(
    title="Refresh Account",
    annotations=IDEMPOTENT_WRITE_ANNOTATIONS,
)
@require_write_consent(
    lambda kw: describe_request(
        "Refresh data for one account. Rate-limited by your bank.",
        [("account", kw.get("account_id"))],
    ),
    automatable=True,
)
async def refresh_account(*, ctx: Context, account_id: str) -> dict[str, Any]:
    """Trigger Akahu to fetch fresh data for one specific account.

    Rate-limited by your bank. Idempotent within rate-limit windows. Use
    when you only need to refresh one account (e.g. checking before a
    payday lookup). Requires write consent unless AKAHU_AUTOMATION_BYPASS=true.

    Returns {"success": bool, "message": str | None, "account_id": str}.

    Args:
        account_id: Akahu account id to refresh.
    """
    result = await deps.get_client().refresh_one(account_id)
    return {"success": result.success, "message": result.message, "account_id": account_id}
