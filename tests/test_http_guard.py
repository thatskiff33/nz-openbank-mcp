"""Host and Origin validation for the HTTP entrypoint (SEC-02)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from key_value.aio.stores.memory import MemoryStore
from pydantic import SecretStr, ValidationError
from starlette.testclient import TestClient

from tests.conftest import STATE_DIR

BEARER = "http_token_test_0123456789abcdef0123"
PUBLIC_HOST = "mcp.example.com"


def _oauth_config() -> Any:
    from nz_openbank_mcp.config import McpOAuthConfig

    return McpOAuthConfig(
        google_client_id="client-id.apps.googleusercontent.com",
        google_client_secret=SecretStr("client-secret"),
        public_base_url=f"https://{PUBLIC_HOST}/openbank-mcp",
        allowed_users="owner@example.com",
        jwt_signing_key=SecretStr("jwt-signing-key-0123456789abcdef0123456789"),
        state_dir=STATE_DIR,
    )


# ---------- NZ_OPENBANK_MCP_ALLOWED_HOSTS ----------


def test_allowed_hosts_parse(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_HOSTS", " mcp.example.com , API.example.com:8443 ,")
    cfg = McpHttpConfig(bearer_token=SecretStr(BEARER))
    assert cfg.allowed_host_list == ["mcp.example.com", "api.example.com:8443"]


def test_allowed_hosts_legacy_alias(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.setenv("OPENBANK_MCP_ALLOWED_HOSTS", "mcp.example.com")
    assert McpHttpConfig(bearer_token=SecretStr(BEARER)).allowed_host_list == ["mcp.example.com"]


def test_allowed_hosts_default_empty(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    assert McpHttpConfig(bearer_token=SecretStr(BEARER)).allowed_host_list == []


@pytest.mark.parametrize(
    "bad",
    [
        "https://mcp.example.com",
        "mcp.example.com/mcp",
        "*.example.com",
        "*",
        "user@mcp.example.com",
        "mcp.example.com:http",
        "mcp.example.com:70000",
        "mcp example.com",
        "mcp.example.com:\uff18\uff10",  # full-width digits
        "mcp.example.com:\u0668\u0660",  # Arabic-Indic digits
    ],
)
def test_allowed_hosts_reject_non_hosts(bad: str) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    with pytest.raises(ValidationError, match="allowed host"):
        McpHttpConfig(bearer_token=SecretStr(BEARER), allowed_hosts=bad)


# ---------- options passed to FastMCP ----------


def test_bearer_guard_without_extra_hosts_is_loopback_only(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import http_guard_options

    cfg = McpHttpConfig(bearer_token=SecretStr(BEARER))
    assert http_guard_options(cfg, None) == {
        "host_origin_protection": True,
        "allowed_hosts": [],
        "allowed_origins": [],
    }


def test_bearer_guard_with_extra_hosts(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import http_guard_options

    cfg = McpHttpConfig(bearer_token=SecretStr(BEARER), allowed_hosts="mcp.example.com:8443")
    assert http_guard_options(cfg, None) == {
        "host_origin_protection": True,
        "allowed_hosts": ["mcp.example.com:8443"],
        "allowed_origins": ["https://mcp.example.com:8443"],
    }


def test_oauth_guard_adds_the_public_host(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import http_guard_options

    cfg = McpHttpConfig(auth_mode="oauth")
    assert http_guard_options(cfg, _oauth_config()) == {
        "host_origin_protection": True,
        "allowed_hosts": [PUBLIC_HOST],
        "allowed_origins": [f"https://{PUBLIC_HOST}"],
    }


# ---------- requests: refused before auth runs ----------


def _bearer_app(**cfg: Any) -> Any:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import build_http_server, http_guard_options

    http_cfg = McpHttpConfig(bearer_token=SecretStr(BEARER), **cfg)
    return build_http_server(http_cfg).http_app(
        path=http_cfg.path, transport="streamable-http", **http_guard_options(http_cfg, None)
    )


def _oauth_app() -> Any:
    from nz_openbank_mcp.config import McpHttpConfig
    from nz_openbank_mcp.server import build_http_server, http_guard_options

    http_cfg = McpHttpConfig(auth_mode="oauth")
    oauth_cfg = _oauth_config()
    return build_http_server(http_cfg, oauth_cfg, oauth_client_storage=MemoryStore()).http_app(
        path=http_cfg.path,
        transport="streamable-http",
        **http_guard_options(http_cfg, oauth_cfg),
    )


def _post(app: Any, host: str, origin: str | None = None) -> int:
    headers = {"host": host}
    if origin is not None:
        headers["origin"] = origin
    with TestClient(app) as client:
        return client.post("/mcp", json={}, headers=headers).status_code


def test_bearer_refuses_a_foreign_host(fake_env: None) -> None:
    assert _post(_bearer_app(), "evil.example") == 421


def test_bearer_refuses_a_proxied_host_until_it_is_allowed(fake_env: None) -> None:
    assert _post(_bearer_app(), PUBLIC_HOST) == 421
    assert _post(_bearer_app(allowed_hosts=PUBLIC_HOST), PUBLIC_HOST) == 401


def test_bearer_refuses_a_foreign_origin(fake_env: None) -> None:
    assert _post(_bearer_app(), "127.0.0.1:8091", "https://evil.example") == 403


def test_bearer_loopback_without_origin_reaches_auth(fake_env: None) -> None:
    assert _post(_bearer_app(), "127.0.0.1:8091") == 401
    assert _post(_bearer_app(), "localhost:8091") == 401


def test_bearer_allowed_host_https_origin_reaches_auth(fake_env: None) -> None:
    app = _bearer_app(allowed_hosts=PUBLIC_HOST)
    assert _post(app, PUBLIC_HOST, f"https://{PUBLIC_HOST}") == 401


def test_oauth_refuses_a_foreign_host_and_origin(fake_env: None) -> None:
    app = _oauth_app()
    assert _post(app, "evil.example") == 421
    assert _post(app, PUBLIC_HOST, "https://evil.example") == 403


def test_oauth_public_host_and_origin_reach_auth(fake_env: None) -> None:
    app = _oauth_app()
    assert _post(app, PUBLIC_HOST) == 401
    assert _post(app, PUBLIC_HOST, f"https://{PUBLIC_HOST}") == 401


# ---------- http_main wiring ----------


def _capture_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from fastmcp import FastMCP

    captured: dict[str, Any] = {}

    def fake_run(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(FastMCP, "run", fake_run)
    return captured


def test_http_main_turns_the_guard_on_and_warns_without_hosts(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp.server import http_main

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", BEARER)
    monkeypatch.delenv("NZ_OPENBANK_MCP_ALLOWED_HOSTS", raising=False)
    captured = _capture_run(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="nz_openbank_mcp.server"):
        http_main()
    assert captured["host_origin_protection"] is True
    assert captured["allowed_hosts"] == []
    assert "NZ_OPENBANK_MCP_ALLOWED_HOSTS" in caplog.text


def test_http_main_passes_configured_hosts_without_warning(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp.server import http_main

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", BEARER)
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_HOSTS", PUBLIC_HOST)
    captured = _capture_run(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="nz_openbank_mcp.server"):
        http_main()
    assert captured["allowed_hosts"] == [PUBLIC_HOST]
    assert captured["allowed_origins"] == [f"https://{PUBLIC_HOST}"]
    assert "NZ_OPENBANK_MCP_ALLOWED_HOSTS" not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "https://*.example.com/openbank-mcp",
        "https://user@mcp.example.com/openbank-mcp",
        "https://mcp example.com/openbank-mcp",
    ],
)
def test_oauth_public_base_url_host_must_be_plain(url: str) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    with pytest.raises(ValidationError, match="plain host"):
        McpOAuthConfig(
            google_client_id="client-id.apps.googleusercontent.com",
            google_client_secret=SecretStr("client-secret"),
            public_base_url=url,
            allowed_users="owner@example.com",
            jwt_signing_key=SecretStr("jwt-signing-key-0123456789abcdef0123456789"),
            state_dir=STATE_DIR,
        )


def test_allowed_hosts_accept_underscores_and_ipv6(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    cfg = McpHttpConfig(bearer_token=SecretStr(BEARER), allowed_hosts="nz_openbank:8091,[::1]:8091")
    assert cfg.allowed_host_list == ["nz_openbank:8091", "[::1]:8091"]


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server/openbank-mcp",
        "/.well-known/oauth-protected-resource/openbank-mcp/mcp",
        "/token",
        "/register",
        "/authorize",
    ],
)
def test_oauth_routes_are_guarded_too(fake_env: None, path: str) -> None:
    """The guard covers OAuth and metadata routes, not only the MCP endpoint."""
    with TestClient(_oauth_app()) as client:
        assert client.get(path, headers={"host": "evil.example"}).status_code == 421
        assert client.get(path, headers={"host": PUBLIC_HOST}).status_code != 421
