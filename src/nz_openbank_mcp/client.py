"""Async HTTP client for Akahu (https://developers.akahu.nz/docs/personal-apps).

Auth model: two headers on every call.
  - Authorization: Bearer <user_token>
  - X-Akahu-Id: <app_token>

Retries: idempotent requests (GET, plus calls that opt in) get 3 attempts on
5xx and httpx.TransportError, with 1s then 2s backoff and no sleep after the
last attempt. Other requests are sent once, because a timed-out POST may
already have taken effect. 429 is retried for every request (Akahu did not
process it), honouring a numeric Retry-After. Other 4xx surfaces immediately.

Paging: transaction iterators stop after MAX_PAGES pages and set `truncated`.

Logging: INFO logs "GET /path -> 200" lines. Auth tokens and API response
bodies are never logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx
from fastmcp.exceptions import ToolError

from nz_openbank_mcp.config import AkahuConfig, get_config
from nz_openbank_mcp.models import (
    Account,
    Me,
    PendingTransaction,
    RefreshResult,
    SupportRequest,
    Transaction,
    VerifyNameResult,
)
from nz_openbank_mcp.safety import MissingCredentialsError

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BASE_BACKOFF = 1.0
_MAX_RETRY_AFTER = 60.0
MAX_PAGES = 20

PageFetcher = Callable[[str | None], Awaitable[tuple[list[Transaction], str | None]]]


class TransactionPages:
    """Async iterator over transactions across cursor pages, capped at MAX_PAGES.

    `truncated` becomes True once iteration stops at the cap with more pages
    still available.
    """

    def __init__(self, fetch: PageFetcher) -> None:
        self._fetch = fetch
        self.truncated = False

    async def __aiter__(self) -> AsyncIterator[Transaction]:
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            items, cursor = await self._fetch(cursor)
            for item in items:
                yield item
            if not cursor:
                return
        self.truncated = True


def _items(data: dict[str, Any], path: str) -> list[Any]:
    items = data.get("items")
    if not isinstance(items, list):
        raise ToolError(f"Akahu returned an unexpected response for {path}: no items list.")
    return items


def _item(data: dict[str, Any], path: str) -> Any:
    if "item" not in data:
        raise ToolError(f"Akahu returned an unexpected response for {path}: no item.")
    return data["item"]


class AkahuClient:
    """Thin wrapper around httpx.AsyncClient with auth, retry, and parsing."""

    def __init__(self, config: AkahuConfig | None = None) -> None:
        self.config = config or get_config()
        if not self.config.is_configured:
            raise MissingCredentialsError(
                "AKAHU_APP_TOKEN and AKAHU_USER_TOKEN must both be set before "
                "calling the Akahu API."
            )
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=self.config.auth_headers,
            timeout=self.config.request_timeout,
        )
        self._closed = False

    async def aclose(self) -> None:
        """Close the underlying httpx client. Safe to call repeatedly."""
        if self._closed:
            return
        await self._client.aclose()
        self._closed = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ---------- core request loop ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        idempotent: bool | None = None,
    ) -> dict[str, Any]:
        """Send one request with retry/backoff. Returns the parsed JSON object.

        `idempotent` defaults to True for GET only; it decides whether
        transport errors and 5xx are retried.
        """
        retry_failures = method == "GET" if idempotent is None else idempotent

        for attempt in range(_MAX_ATTEMPTS):
            last_attempt = attempt == _MAX_ATTEMPTS - 1
            try:
                response = await self._client.request(method, path, params=params, json=json)
            except httpx.TransportError as exc:
                logger.warning(
                    "%s %s transport error (%s); attempt %d/%d",
                    method,
                    path,
                    type(exc).__name__,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                )
                if last_attempt or not retry_failures:
                    raise
                await asyncio.sleep(_BASE_BACKOFF * (2**attempt))
                continue

            logger.info("%s %s -> %d", method, path, response.status_code)

            if response.status_code < 400:
                return self._json_object(response, method, path)

            if response.status_code == 429 and not last_attempt:
                delay = self._retry_after_seconds(response, default=_BASE_BACKOFF * (2**attempt))
                logger.warning("%s %s rate-limited; sleeping %.1fs", method, path, delay)
                await asyncio.sleep(delay)
                continue

            if 500 <= response.status_code < 600 and retry_failures and not last_attempt:
                logger.warning(
                    "%s %s server error %d; attempt %d/%d",
                    method,
                    path,
                    response.status_code,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                )
                await asyncio.sleep(_BASE_BACKOFF * (2**attempt))
                continue

            response.raise_for_status()

        raise RuntimeError("Akahu request retry loop exhausted unexpectedly.")  # pragma: no cover

    @staticmethod
    def _json_object(response: httpx.Response, method: str, path: str) -> dict[str, Any]:
        """Parse a success body, which Akahu always sends as a JSON object."""
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ToolError(
                f"Akahu returned an unexpected response for {method} {path} "
                f"(HTTP {response.status_code}): expected a JSON object."
            )
        return data

    @staticmethod
    def _retry_after_seconds(response: httpx.Response, *, default: float) -> float:
        """Parse Retry-After in seconds. Fall back to `default` if absent or non-numeric."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return default
        try:
            delay = float(raw)
        except ValueError:
            return default
        if delay < 0:
            return default
        return min(delay, _MAX_RETRY_AFTER)

    @staticmethod
    def _path_segment(value: str, *, name: str) -> str:
        """Encode a caller-supplied value as one URL path segment."""
        if not value:
            raise ValueError(f"{name} must not be empty")
        return quote(value, safe="")

    # ---------- read endpoints ----------

    async def get_me(self) -> Me:
        data = await self._request("GET", "/me")
        return Me.model_validate(_item(data, "/me"))

    async def list_accounts(self) -> list[Account]:
        data = await self._request("GET", "/accounts")
        return [Account.model_validate(item) for item in _items(data, "/accounts")]

    async def get_account(self, account_id: str) -> Account:
        path = f"/accounts/{self._path_segment(account_id, name='account_id')}"
        data = await self._request("GET", path)
        return Account.model_validate(_item(data, path))

    async def _transaction_page(
        self,
        path: str,
        *,
        start: str | None,
        end: str | None,
        cursor: str | None,
    ) -> tuple[list[Transaction], str | None]:
        """One page of settled transactions and the next cursor (None on the last page)."""
        params: dict[str, Any] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", path, params=params or None)
        items = [Transaction.model_validate(item) for item in _items(data, path)]
        cursor_block = data.get("cursor")
        next_cursor = cursor_block.get("next") if isinstance(cursor_block, dict) else None
        return items, next_cursor or None

    async def get_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        cursor: str | None = None,
    ) -> list[Transaction]:
        items, _ = await self._transaction_page(
            "/transactions", start=start, end=end, cursor=cursor
        )
        return items

    async def get_transaction(self, transaction_id: str) -> Transaction:
        path = f"/transactions/{self._path_segment(transaction_id, name='transaction_id')}"
        data = await self._request("GET", path)
        return Transaction.model_validate(_item(data, path))

    def iter_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> TransactionPages:
        """Transactions across pages, up to MAX_PAGES."""
        return TransactionPages(
            lambda cursor: self._transaction_page(
                "/transactions", start=start, end=end, cursor=cursor
            )
        )

    async def get_pending_transactions(self) -> list[PendingTransaction]:
        """All pending transactions across the user's connected accounts."""
        path = "/transactions/pending"
        data = await self._request("GET", path)
        return [PendingTransaction.model_validate(item) for item in _items(data, path)]

    async def get_account_pending_transactions(self, account_id: str) -> list[PendingTransaction]:
        """Pending transactions for one specific account."""
        path = f"/accounts/{self._path_segment(account_id, name='account_id')}/transactions/pending"
        data = await self._request("GET", path)
        return [PendingTransaction.model_validate(item) for item in _items(data, path)]

    async def get_account_transactions(
        self,
        account_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Transaction], str | None]:
        """Settled transactions for one account, paged.

        Returns (items, next_cursor). next_cursor is None on the last page.
        """
        path = f"/accounts/{self._path_segment(account_id, name='account_id')}/transactions"
        return await self._transaction_page(path, start=start, end=end, cursor=cursor)

    def iter_account_transactions(
        self,
        account_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> TransactionPages:
        """Transactions for one account across pages, up to MAX_PAGES."""
        return TransactionPages(
            lambda cursor: self.get_account_transactions(
                account_id, start=start, end=end, cursor=cursor
            )
        )

    async def get_transactions_by_ids(self, ids: list[str]) -> list[Transaction]:
        """Batch lookup by transaction id.

        Akahu wire shape: POST /transactions/ids with body = JSON array of strings.
        See https://developers.akahu.nz/reference/post_transactions-ids. A
        read, so it is retried like a GET.
        """
        path = "/transactions/ids"
        data = await self._request("POST", path, json=ids, idempotent=True)
        return [Transaction.model_validate(item) for item in _items(data, path)]

    # ---------- write endpoints ----------

    # Refreshes are retried: repeating one inside Akahu's rate-limit window is harmless.

    async def refresh_all(self) -> RefreshResult:
        data = await self._request("POST", "/refresh", idempotent=True)
        return RefreshResult.model_validate(data)

    async def refresh_one(self, account_id: str) -> RefreshResult:
        account = self._path_segment(account_id, name="account_id")
        data = await self._request("POST", f"/refresh/{account}", idempotent=True)
        return RefreshResult.model_validate(data)

    async def report_transaction_issue(
        self,
        transaction_id: str,
        *,
        issue_type: str,
        fields: list[str] | None = None,
        comment: str | None = None,
        other_transaction_id: str | None = None,
    ) -> SupportRequest:
        """Submit a support ticket about a transaction.

        Wire shape per https://developers.akahu.nz/reference/post_support-transaction-id:
          path:  /support/{transaction_id}
          body:  {"type": ..., "other_id": ..., "fields": [...], "comment": "..."}
        """
        body: dict[str, Any] = {"type": issue_type}
        if fields:
            body["fields"] = fields
        if comment:
            body["comment"] = comment
        if other_transaction_id:
            body["other_id"] = other_transaction_id
        transaction = self._path_segment(transaction_id, name="transaction_id")
        data = await self._request("POST", f"/support/{transaction}", json=body)
        return SupportRequest.model_validate(data)

    async def verify_name(
        self,
        *,
        family_name: str,
        given_name: str | None = None,
        middle_name: str | None = None,
        initials: list[str] | None = None,
        account_id: str | None = None,
    ) -> VerifyNameResult:
        """Ask Akahu to confirm whether the given name matches the account holder.

        Wire shape per https://developers.akahu.nz/reference/post_verify-name :
          path:  /verify/name             (when account_id is None - all sources)
                 /verify/name/{account_id} (scoped to one account)
          body:  required `family_name`; optional `given_name`, `middle_name`,
                 `initials`.

        Requires the relevant Personal-App scope grant; returns 403 without it.
        """
        body: dict[str, Any] = {"family_name": family_name}
        if given_name:
            body["given_name"] = given_name
        if middle_name:
            body["middle_name"] = middle_name
        if initials:
            body["initials"] = initials
        path = "/verify/name"
        if account_id is not None:
            account = self._path_segment(account_id, name="account_id")
            path = f"/verify/name/{account}"
        data = await self._request("POST", path, json=body)
        return VerifyNameResult.model_validate(data)
