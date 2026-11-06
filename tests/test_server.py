"""Tests for the root server: composition, namespaces, startup banner."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp.server.auth import AccessToken
from key_value.aio.stores.memory import MemoryStore
from pydantic import SecretStr
from starlette.testclient import TestClient

from tests.conftest import STATE_DIR

BEARER = "http_token_test_0123456789abcdef0123"
SIGNING_KEY = "jwt_signing_key_test_0123456789abcdef"


def _oauth_config() -> Any:
    from nz_openbank_mcp.config import McpOAuthConfig

    return McpOAuthConfig(
        google_client_id="google-client.apps.googleusercontent.com",
        google_client_secret="google-secret",
        public_base_url="https://mcp.example.com/openbank-mcp",
        allowed_users="owner@example.com",
        jwt_signing_key=SIGNING_KEY,
        state_dir=STATE_DIR,
    )


async def test_root_server_exposes_all_14_tools(fake_env: None) -> None:
    from nz_openbank_mcp.server import build_server

    mcp = build_server()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # accounts (6)
        "acct_list_accounts",
        "acct_get_account",
        "acct_get_account_balance",
        "acct_get_pending_transactions",
        "acct_refresh_all_accounts",
        "acct_refresh_account",
        # transactions (6)
        "txn_get_transactions",
        "txn_get_transaction",
        "txn_get_transactions_by_ids",
        "txn_get_pending_transactions",
        "txn_search_transactions",
        "txn_report_transaction_issue",
        # identity (2) -- /categories, /parties, /identity/{id}/verify-name are app-scoped
        "id_get_me",
        "id_verify_name",
    }
    assert names == expected


async def test_root_server_sets_chatgpt_instructions(fake_env: None) -> None:
    from nz_openbank_mcp.server import SERVER_INSTRUCTIONS, build_server

    mcp = build_server()
    assert "last-month transactions" in SERVER_INSTRUCTIONS
    assert len(SERVER_INSTRUCTIONS[:512]) == len(SERVER_INSTRUCTIONS)
    assert mcp._mcp_server.instructions == SERVER_INSTRUCTIONS


async def test_all_tools_have_apps_sdk_titles_and_annotations(fake_env: None) -> None:
    """ChatGPT Apps SDK treats missing tool annotations as a validation error."""
    from nz_openbank_mcp.server import build_server

    expected_write_tools = {
        "acct_refresh_all_accounts",
        "acct_refresh_account",
        "txn_report_transaction_issue",
        "id_verify_name",
    }
    idempotent_write_tools = {
        "acct_refresh_all_accounts",
        "acct_refresh_account",
    }

    mcp = build_server()
    tools = await mcp.list_tools()

    for tool in tools:
        assert tool.title, f"{tool.name} is missing a human-readable title"
        assert tool.annotations is not None, f"{tool.name} is missing annotations"

        annotations = tool.annotations
        wire = annotations.model_dump(by_alias=True, exclude_none=True)
        if tool.name in expected_write_tools:
            assert annotations.read_only_hint is False
            assert annotations.open_world_hint is False
            assert annotations.destructive_hint is False
            if tool.name in idempotent_write_tools:
                assert annotations.idempotent_hint is True
                assert wire["idempotentHint"] is True
            else:
                assert annotations.idempotent_hint is None
            assert wire["readOnlyHint"] is False
        else:
            assert annotations.read_only_hint is True
            assert annotations.open_world_hint is None
            assert annotations.destructive_hint is None
            assert wire == {"readOnlyHint": True}


async def test_http_server_exposes_all_14_tools_with_auth(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.http_auth import StaticBearerAuthProvider
    from nz_openbank_mcp.server import build_http_server

    mcp = build_http_server(McpHttpConfig(bearer_token=SecretStr(BEARER)))
    tools = await mcp.list_tools()
    assert len(tools) == 14
    assert isinstance(mcp.auth, StaticBearerAuthProvider)


async def test_http_server_exposes_all_14_tools_with_oauth(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider
    from nz_openbank_mcp.server import build_http_server

    mcp = build_http_server(
        McpHttpConfig(auth_mode="oauth"),
        _oauth_config(),
        oauth_client_storage=MemoryStore(),
    )

    tools = await mcp.list_tools()
    assert len(tools) == 14
    assert isinstance(mcp.auth, AllowlistedGoogleOAuthProvider)


def test_http_server_oauth_mode_loads_oauth_env(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider
    from nz_openbank_mcp.server import build_http_server

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv(
        "NZ_OPENBANK_MCP_PUBLIC_BASE_URL",
        "https://mcp.example.com/openbank-mcp",
    )
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_USERS", "owner@example.com")
    monkeypatch.setenv("NZ_OPENBANK_MCP_JWT_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("NZ_OPENBANK_MCP_STATE_DIR", STATE_DIR)

    mcp = build_http_server(
        McpHttpConfig(auth_mode="oauth"),
        oauth_client_storage=MemoryStore(),
    )

    assert isinstance(mcp.auth, AllowlistedGoogleOAuthProvider)


async def test_http_bearer_auth_provider_accepts_only_expected_token() -> None:
    from nz_openbank_mcp.http_auth import StaticBearerAuthProvider

    provider = StaticBearerAuthProvider(SecretStr(BEARER))
    assert await provider.verify_token("wrong_token") is None

    access = await provider.verify_token(BEARER)
    assert access is not None
    assert access.client_id == "nz-openbank-mcp-http"
    assert access.scopes == []


def test_oauth_provider_allowlist_accepts_users_and_domains() -> None:
    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["Owner@Example.com"],
        allowed_domains=["Example.org"],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )

    assert provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={"email": "owner@example.com", "email_verified": True},
        )
    )
    assert provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={
                "email": "person@example.org",
                "email_verified": "true",
                "google_user_data": {"hd": "Example.org"},
            },
        )
    )


def test_oauth_provider_allowlist_rejects_unverified_or_unknown_email() -> None:
    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["owner@example.com"],
        allowed_domains=["example.org"],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )

    assert not provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={"email": "owner@example.com", "email_verified": False},
        )
    )
    assert not provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={"email": "owner@example.com", "email_verified": "false"},
        )
    )
    assert not provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={"email": 123, "email_verified": True},
        )
    )
    assert not provider._is_access_allowed(
        AccessToken(
            token="token",
            client_id="google-user",
            scopes=[],
            claims={"email": "stranger@example.net", "email_verified": object()},
        )
    )


async def test_oauth_provider_load_access_token_filters_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.server.auth.providers.google import GoogleProvider

    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["owner@example.com"],
        allowed_domains=[],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )
    allowed = AccessToken(
        token="token",
        client_id="google-user",
        scopes=[],
        claims={"email": "owner@example.com", "email_verified": True},
    )
    denied = AccessToken(
        token="token",
        client_id="google-user",
        scopes=[],
        claims={"email": "stranger@example.com", "email_verified": True},
    )

    async def fake_allowed(self: object, token: str) -> AccessToken | None:
        return allowed

    async def fake_denied(self: object, token: str) -> AccessToken | None:
        return denied

    async def fake_missing(self: object, token: str) -> AccessToken | None:
        return None

    monkeypatch.setattr(GoogleProvider, "load_access_token", fake_allowed)
    assert await provider.load_access_token("allowed-token") == allowed

    monkeypatch.setattr(GoogleProvider, "load_access_token", fake_denied)
    assert await provider.load_access_token("denied-token") is None

    monkeypatch.setattr(GoogleProvider, "load_access_token", fake_missing)
    assert await provider.load_access_token("missing-token") is None


async def test_oauth_provider_exchange_authorization_code_enforces_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.server.auth.providers.google import GoogleProvider
    from mcp.server.auth.provider import TokenError
    from mcp.shared.auth import OAuthToken

    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["owner@example.com"],
        allowed_domains=[],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )
    access = AccessToken(
        token="issued-token",
        client_id="google-user",
        scopes=[],
        claims={"email": "owner@example.com", "email_verified": True},
    )

    async def fake_exchange(
        self: object,
        client: object,
        authorization_code: object,
    ) -> OAuthToken:
        return OAuthToken(access_token="issued-token")

    async def fake_allowed(self: object, token: str) -> AccessToken | None:
        return access

    async def fake_denied(self: object, token: str) -> AccessToken | None:
        return None

    monkeypatch.setattr(GoogleProvider, "exchange_authorization_code", fake_exchange)
    monkeypatch.setattr(AllowlistedGoogleOAuthProvider, "load_access_token", fake_allowed)
    unknown_code: Any = SimpleNamespace(code="not-stored")
    oauth_token = await provider.exchange_authorization_code(object(), unknown_code)  # type: ignore[arg-type]
    assert oauth_token.access_token == "issued-token"

    monkeypatch.setattr(AllowlistedGoogleOAuthProvider, "load_access_token", fake_denied)
    with pytest.raises(TokenError, match="not allowed"):
        await provider.exchange_authorization_code(object(), unknown_code)  # type: ignore[arg-type]


def test_http_app_rejects_missing_bearer(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(bearer_token=SecretStr(BEARER))
    app = build_http_server(cfg).http_app(
        path=cfg.path,
        transport="streamable-http",
    )

    with TestClient(app) as client:
        response = client.post(cfg.path, json={})

    assert response.status_code == 401


def test_oauth_http_app_exposes_metadata_and_rejects_missing_token(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    app = build_http_server(
        cfg,
        _oauth_config(),
        oauth_client_storage=MemoryStore(),
    ).http_app(
        path=cfg.path,
        transport="streamable-http",
    )

    with TestClient(app) as client:
        protected = client.get("/.well-known/oauth-protected-resource/openbank-mcp/mcp")
        authorization = client.get("/.well-known/oauth-authorization-server/openbank-mcp")
        unauthenticated = client.post(cfg.path, json={})

    protected_metadata = protected.json()
    authorization_metadata = authorization.json()

    assert protected.status_code == 200
    assert protected_metadata["resource"] == "https://mcp.example.com/openbank-mcp/mcp"
    assert protected_metadata["authorization_servers"] == ["https://mcp.example.com/openbank-mcp"]
    assert authorization.status_code == 200
    assert authorization_metadata["issuer"] == "https://mcp.example.com/openbank-mcp"
    assert authorization_metadata["authorization_endpoint"] == (
        "https://mcp.example.com/openbank-mcp/authorize"
    )
    assert authorization_metadata["token_endpoint"] == (
        "https://mcp.example.com/openbank-mcp/token"
    )
    assert authorization_metadata["registration_endpoint"] == (
        "https://mcp.example.com/openbank-mcp/register"
    )
    assert unauthenticated.status_code == 401


def test_oauth_provider_without_path_does_not_add_path_aware_alias() -> None:
    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://example.com",
        allowed_users=["owner@example.com"],
        allowed_domains=[],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )

    route_paths = {route.path for route in provider.get_routes("/mcp")}
    assert "/.well-known/oauth-authorization-server" in route_paths
    assert "/.well-known/oauth-authorization-server/" not in route_paths


def test_oauth_provider_keeps_routes_when_base_metadata_route_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.server.auth.providers.google import GoogleProvider
    from starlette.responses import Response
    from starlette.routing import Route

    from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

    async def endpoint(request: object) -> Response:
        return Response()

    def fake_routes(self: object, mcp_path: str | None = None) -> list[Route]:
        return [Route("/other", endpoint=endpoint)]

    monkeypatch.setattr(GoogleProvider, "get_routes", fake_routes)
    provider = AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["owner@example.com"],
        allowed_domains=[],
        jwt_signing_key=SIGNING_KEY,
        allowed_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        client_storage=MemoryStore(),
    )

    route_paths = [route.path for route in provider.get_routes("/mcp")]
    assert route_paths == ["/other"]


def test_access_claims_rejects_non_mapping_claims() -> None:
    from nz_openbank_mcp.http_auth import _access_claims

    token = type("Token", (), {"claims": ["not", "a", "mapping"]})()

    assert _access_claims(token) == {}


async def test_composed_plugin_names_fit_kiro_limit(fake_env: None) -> None:
    """Guard: marketplace-plugin-composed names must stay within Kiro's 64-char cap."""
    from nz_openbank_mcp.server import build_server

    mcp = build_server()
    tools = await mcp.list_tools()
    prefix = "mcp__plugin_nz-openbank-mcp_akahu__"
    for t in tools:
        composed = prefix + t.name
        assert len(composed) <= 64, f"{composed} is {len(composed)} chars"


def test_startup_banner_when_bypass_off(
    writable_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp.server import log_startup_banner

    with caplog.at_level(logging.INFO, logger="nz_openbank_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "all writes require confirmation" in blob.lower()


def test_startup_banner_when_bypass_on(bypass_env: None, caplog: pytest.LogCaptureFixture) -> None:
    from nz_openbank_mcp.server import log_startup_banner

    with caplog.at_level(logging.WARNING, logger="nz_openbank_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "automation bypass enabled" in blob.lower()
    assert "refresh_all_accounts" in blob
    assert "refresh_account" in blob


def test_startup_banner_when_readonly(fake_env: None, caplog: pytest.LogCaptureFixture) -> None:
    from nz_openbank_mcp.server import log_startup_banner

    with caplog.at_level(logging.INFO, logger="nz_openbank_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "read-only" in blob.lower()


def test_configure_logging_suppresses_sensitive_http_client_logs() -> None:
    from nz_openbank_mcp.server import configure_logging

    old_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in ("httpx", "httpcore", "httpx2", "httpcore2", "uvicorn.access")
    }
    try:
        for logger_name in old_levels:
            logging.getLogger(logger_name).setLevel(logging.NOTSET)

        configure_logging("INFO")

        for logger_name in old_levels:
            assert logging.getLogger(logger_name).level == logging.WARNING
    finally:
        for logger_name, level in old_levels.items():
            logging.getLogger(logger_name).setLevel(level)


def test_main_constructs_and_runs(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() must build the server and call .run(); we verify the call site."""
    from nz_openbank_mcp import server

    called: dict[str, object] = {}

    def fake_run(self: object, show_banner: bool | None = None) -> None:
        called["show_banner"] = show_banner

    monkeypatch.setattr(server.FastMCP, "run", fake_run)
    server.main()
    assert called == {"show_banner": False}


def test_http_main_constructs_and_runs(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """http_main() must build the auth server and use Streamable HTTP."""
    from nz_openbank_mcp import server

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", BEARER)
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_PORT", "8091")
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_PATH", "/mcp")

    called: dict[str, object] = {}

    def fake_run(
        self: object,
        transport: str | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: object,
    ) -> None:
        called["transport"] = transport
        called["show_banner"] = show_banner
        called["transport_kwargs"] = transport_kwargs

    monkeypatch.setattr(server.FastMCP, "run", fake_run)
    server.http_main()

    assert called == {
        "transport": "streamable-http",
        "show_banner": False,
        "transport_kwargs": {
            "host": "127.0.0.1",
            "port": 8091,
            "path": "/mcp",
            "uvicorn_config": {"access_log": False},
            "host_origin_protection": True,
            "allowed_hosts": [],
            "allowed_origins": [],
        },
    }


async def test_server_shutdown_closes_shared_client(fake_env: None) -> None:
    from fastmcp import Client

    from nz_openbank_mcp import deps
    from nz_openbank_mcp.server import build_server

    deps._client = None
    async with Client(build_server()) as client:
        await client.list_tools()
        shared = deps.get_client()
        assert not shared._client.is_closed
    assert shared._client.is_closed
    assert deps._client is None


def test_config_is_read_once_per_process(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_openbank_mcp.config import get_config

    first = get_config()
    monkeypatch.setenv("AKAHU_READ_ONLY", "false")
    assert get_config() is first
    assert first.read_only is True


async def test_oauth_state_is_culled_while_the_server_runs(
    fake_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from fastmcp import Client

    from nz_openbank_mcp.http_auth import DurableOAuthStorage
    from nz_openbank_mcp.server import build_server

    state = MagicMock(spec=DurableOAuthStorage)
    state.cull = AsyncMock(side_effect=[RuntimeError("disk"), None])
    with caplog.at_level(logging.WARNING):
        async with Client(build_server(oauth_state=state)) as client:
            await client.list_tools()
            await asyncio.sleep(0)
    state.cull.assert_awaited_once()
    assert "OAuth state cull failed" in caplog.text


async def test_cull_loop_repeats_on_its_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import nz_openbank_mcp.server as server_mod

    monkeypatch.setattr(server_mod, "STATE_CULL_INTERVAL_SECONDS", 0)
    state = MagicMock()
    state.cull = AsyncMock()
    task = asyncio.create_task(server_mod._cull_periodically(state))
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    assert state.cull.await_count >= 2


def test_http_server_culls_only_durable_storage(
    fake_env: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from key_value.aio.stores.memory import MemoryStore

    import nz_openbank_mcp.server as server_mod
    from nz_openbank_mcp.config import McpHttpConfig, McpOAuthConfig
    from nz_openbank_mcp.http_auth import durable_client_storage

    seen: list[object] = []
    real = server_mod.build_server

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs.get("oauth_state"))
        return real(**kwargs)

    monkeypatch.setattr(server_mod, "build_server", spy)
    oauth = McpOAuthConfig(
        google_client_id="google-client.apps.googleusercontent.com",
        google_client_secret="google-secret",
        public_base_url="https://mcp.example.com/openbank-mcp",
        allowed_users="owner@example.com",
        jwt_signing_key="jwt_signing_key_test_0123456789abcdef",
        state_dir=str(tmp_path),
    )
    cfg = McpHttpConfig(auth_mode="oauth")
    durable = durable_client_storage(tmp_path, "jwt_signing_key_test_0123456789abcdef")
    server_mod.build_http_server(cfg, oauth, oauth_client_storage=durable)
    server_mod.build_http_server(cfg, oauth, oauth_client_storage=MemoryStore())
    assert seen == [durable, None]
