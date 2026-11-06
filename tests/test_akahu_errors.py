"""Akahu errors say what to do and never carry response data (PRV-02, DX-02)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from nz_openbank_mcp.client import AkahuHTTPError
from tests.conftest import load_fixture

# Values that must never appear in an error or a log line.
SECRET_NAME = "Joint with Pat Example"
SECRET_ACCOUNT = "12-3456-7890123-00"
SECRET_AMOUNT = "98765.43"


def _bad_account() -> dict[str, Any]:
    item = dict(load_fixture("accounts")["items"][0])
    del item["type"]
    item["name"] = SECRET_NAME
    item["formatted_account"] = SECRET_ACCOUNT
    item["balance"] = {"currency": "NZD", "current": float(SECRET_AMOUNT)}
    return item


@pytest_asyncio.fixture
async def real_client(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    from nz_openbank_mcp import deps

    monkeypatch.setattr(deps, "_client", None)
    yield
    await deps.aclose_client()


# ---------- response validation (PRV-02) ----------


async def test_validation_error_names_the_field_without_values(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/accounts").mock(
        return_value=httpx.Response(200, json={"success": True, "items": [_bad_account()]})
    )
    with pytest.raises(ToolError) as excinfo:
        await akahu_client.list_accounts()
    message = str(excinfo.value)
    assert "Account" in message
    assert "/accounts" in message
    assert "type" in message
    for secret in (SECRET_NAME, SECRET_ACCOUNT, SECRET_AMOUNT):
        assert secret not in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


async def test_validation_error_through_a_tool_leaks_nothing_to_model_or_logs(
    real_client: None, respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp.server import build_server

    respx_mock.get("/accounts").mock(
        return_value=httpx.Response(200, json={"success": True, "items": [_bad_account()]})
    )
    respx_mock.get("/transactions").mock(
        return_value=httpx.Response(200, json=load_fixture("transactions"))
    )
    with caplog.at_level(logging.DEBUG):
        async with Client(build_server()) as c:
            result = await c.call_tool("txn_get_transactions", {}, raise_on_error=False)
    assert result.is_error
    text = result.content[0].text  # type: ignore[union-attr]
    logged = "\n".join(
        r.getMessage() + (logging.Formatter().formatException(r.exc_info) if r.exc_info else "")
        for r in caplog.records
    )
    for secret in (SECRET_NAME, SECRET_ACCOUNT, SECRET_AMOUNT):
        assert secret not in text
        assert secret not in logged


async def test_validation_error_lists_at_most_three_fields(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/accounts").mock(
        return_value=httpx.Response(200, json={"success": True, "items": [{}]})
    )
    with pytest.raises(
        ToolError, match=r"_id missing; name missing; status missing \(and 1 more\)"
    ):
        await akahu_client.list_accounts()


@pytest.mark.parametrize(
    ("method", "call", "route", "body"),
    [
        ("get", "get_me", "/me", {"success": True, "item": {"email": "x"}}),
        ("get", "get_account", "/accounts/acc_1", {"success": True, "item": {"_id": "a"}}),
        ("post", "refresh_all", "/refresh", {"message": "no success field"}),
    ],
)
async def test_every_parse_site_uses_the_safe_error(
    akahu_client: Any,
    respx_mock: respx.MockRouter,
    method: str,
    call: str,
    route: str,
    body: dict[str, Any],
) -> None:
    getattr(respx_mock, method)(route).mock(return_value=httpx.Response(200, json=body))
    args = ("acc_1",) if call == "get_account" else ()
    with pytest.raises(ToolError, match="Akahu returned an unexpected"):
        await getattr(akahu_client, call)(*args)


# ---------- HTTP status errors (DX-02) ----------


async def test_401_tells_the_user_to_check_the_tokens(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/me").mock(return_value=httpx.Response(401, json={"message": "bad"}))
    with pytest.raises(AkahuHTTPError, match="AKAHU_USER_TOKEN and AKAHU_APP_TOKEN") as excinfo:
        await akahu_client.get_me()
    assert excinfo.value.status_code == 401


async def test_403_on_name_check_explains_the_scope(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post("/verify/name/acc_1").mock(return_value=httpx.Response(403))
    with pytest.raises(AkahuHTTPError, match=r"my\.akahu\.nz/developers") as excinfo:
        await akahu_client.verify_name(family_name="Person", account_id="acc_1")
    assert excinfo.value.status_code == 403


async def test_other_403_says_the_endpoint_is_not_available(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/me").mock(return_value=httpx.Response(403))
    with pytest.raises(AkahuHTTPError, match="not available to your Personal App"):
        await akahu_client.get_me()


async def test_404_keeps_status_and_path_but_not_the_body(
    akahu_client: Any, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/accounts/acc_missing").mock(
        return_value=httpx.Response(404, json={"message": f"{SECRET_NAME} not found"})
    )
    with pytest.raises(AkahuHTTPError) as excinfo:
        await akahu_client.get_account("acc_missing")
    message = str(excinfo.value)
    assert "404" in message
    assert "GET /accounts/acc_missing" in message
    assert SECRET_NAME not in message
    assert excinfo.value.status_code == 404


async def test_exhausted_429_says_to_wait(
    akahu_client: Any, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nz_openbank_mcp.client as client_mod

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", no_sleep)
    respx_mock.get("/me").mock(return_value=httpx.Response(429))
    with pytest.raises(AkahuHTTPError, match="rate limit"):
        await akahu_client.get_me()


async def test_exhausted_5xx_says_to_try_later(
    akahu_client: Any, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nz_openbank_mcp.client as client_mod

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", no_sleep)
    respx_mock.get("/me").mock(return_value=httpx.Response(503))
    with pytest.raises(AkahuHTTPError, match="try again later") as excinfo:
        await akahu_client.get_me()
    assert excinfo.value.status_code == 503
