"""OAuth hardening: hosted-domain allowlist, redirect allowlist, keys, storage."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
from fastmcp.server.auth import AccessToken
from key_value.aio.stores.memory import MemoryStore
from pydantic import ValidationError
from starlette.testclient import TestClient

from nz_openbank_mcp.config import DEFAULT_ALLOWED_REDIRECT_URIS, McpHttpConfig, McpOAuthConfig
from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider, durable_client_storage

SIGNING_KEY = "jwt_signing_key_test_0123456789abcdef"


def _oauth_config(**overrides: Any) -> McpOAuthConfig:
    values: dict[str, Any] = {
        "google_client_id": "google-client.apps.googleusercontent.com",
        "google_client_secret": "google-secret",
        "public_base_url": "https://mcp.example.com/openbank-mcp",
        "allowed_users": "owner@example.com",
        "jwt_signing_key": SIGNING_KEY,
        "state_dir": "/var/lib/nz-openbank-mcp",
    }
    values.update(overrides)
    return McpOAuthConfig(**values)


def _provider(**overrides: Any) -> AllowlistedGoogleOAuthProvider:
    values: dict[str, Any] = {
        "client_id": "google-client",
        "client_secret": "google-secret",
        "base_url": "https://mcp.example.com/openbank-mcp",
        "allowed_users": ["owner@example.com"],
        "allowed_domains": ["example.org"],
        "jwt_signing_key": SIGNING_KEY,
        "allowed_redirect_uris": list(DEFAULT_ALLOWED_REDIRECT_URIS),
        "client_storage": MemoryStore(),
    }
    values.update(overrides)
    return AllowlistedGoogleOAuthProvider(**values)


def _access(email: str, user_data: object = None) -> AccessToken:
    claims: dict[str, object] = {"email": email, "email_verified": True}
    if user_data is not None:
        claims["google_user_data"] = user_data
    return AccessToken(token="t", client_id="google-user", scopes=[], claims=claims)


def test_consumer_account_on_allowed_domain_is_refused() -> None:
    provider = _provider()

    assert not provider._is_access_allowed(_access("former.staff@example.org"))
    assert not provider._is_access_allowed(
        _access("former.staff@example.org", {"email": "former.staff@example.org"})
    )


def test_hosted_domain_match_is_allowed() -> None:
    provider = _provider()

    assert provider._is_access_allowed(_access("staff@example.org", {"hd": "example.org"}))
    assert provider._is_access_allowed(_access("staff@alias.example", {"hd": " Example.ORG "}))


def test_exact_allowlisted_email_without_hd_is_allowed() -> None:
    provider = _provider()

    assert provider._is_access_allowed(_access("Owner@Example.com"))


@pytest.mark.parametrize(
    "user_data",
    [{"hd": "attacker.example"}, {"hd": ""}, {"hd": 123}, ["hd", "example.org"]],
)
def test_hosted_domain_mismatch_or_malformed_is_refused(user_data: object) -> None:
    provider = _provider()

    assert not provider._is_access_allowed(_access("staff@example.org", user_data))


def test_top_level_hd_claim_is_not_trusted() -> None:
    provider = _provider()
    token = AccessToken(
        token="t",
        client_id="google-user",
        scopes=[],
        claims={"email": "x@example.org", "email_verified": True, "hd": "example.org"},
    )

    assert not provider._is_access_allowed(token)


def _register(client: TestClient, redirect_uri: str) -> int:
    response = client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "client_name": "test-client",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    return response.status_code


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://attacker.example/callback",
        "https://claude.ai.attacker.example/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/other",
        "http://claude.ai/api/mcp/auth_callback",
        "http://localhost@attacker.example/callback",
        "http://192.168.1.10:3000/callback",
        "https://chatgpt.com/connector/oauth/abc123",
    ],
)
def test_unlisted_redirect_uri_is_rejected_at_registration(
    fake_env: None, redirect_uri: str
) -> None:
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    app = build_http_server(cfg, _oauth_config(), oauth_client_storage=MemoryStore()).http_app(
        path=cfg.path, transport="streamable-http"
    )

    with TestClient(app) as client:
        assert _register(client, redirect_uri) == 400


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "http://localhost:3118/callback",
        "http://127.0.0.1:50123/callback",
    ],
)
def test_supported_connector_redirect_uris_register(fake_env: None, redirect_uri: str) -> None:
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    app = build_http_server(cfg, _oauth_config(), oauth_client_storage=MemoryStore()).http_app(
        path=cfg.path, transport="streamable-http"
    )

    with TestClient(app) as client:
        assert _register(client, redirect_uri) == 201


def test_redirect_allowlist_is_configurable(fake_env: None) -> None:
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    oauth = _oauth_config(allowed_redirect_uris="https://claude.ai/api/mcp/auth_callback")
    app = build_http_server(cfg, oauth, oauth_client_storage=MemoryStore()).http_app(
        path=cfg.path, transport="streamable-http"
    )

    with TestClient(app) as client:
        assert _register(client, "https://claude.ai/api/mcp/auth_callback") == 201
        assert _register(client, "http://localhost:3118/callback") == 400


@pytest.mark.parametrize("key", ["", "short", " " * 40, "k" * 31])
def test_oauth_requires_signing_key_of_32_bytes(key: str) -> None:
    with pytest.raises(ValidationError, match="NZ_OPENBANK_MCP_JWT_SIGNING_KEY"):
        _oauth_config(jwt_signing_key=key)


def test_signing_key_hidden_from_repr() -> None:
    assert SIGNING_KEY not in repr(_oauth_config())


@pytest.mark.parametrize("state_dir", ["", "var/lib/nz-openbank-mcp", "./state"])
def test_oauth_requires_absolute_state_dir(state_dir: str) -> None:
    with pytest.raises(ValidationError, match="NZ_OPENBANK_MCP_STATE_DIR"):
        _oauth_config(state_dir=state_dir)


@pytest.mark.parametrize(
    ("patterns", "message"),
    [
        ("", "must not be empty"),
        (" , ", "must not be empty"),
        ("http://example.com/callback", "https or http loopback"),
        ("ftp://claude.ai/cb", "https or http loopback"),
        ("https://*.example.com/cb", "wildcard the host"),
        ("https://user@claude.ai/cb", "plain URL"),
        ("https://claude.ai/cb?x=1", "plain URL"),
        ("https://claude.ai/cb#x", "plain URL"),
        ("https:///cb", "plain URL"),
        ("https://claude.ai", "must include a path"),
        ("https://claude.ai/", "must include a path"),
        ("https://claude.ai/*", "must not wildcard the path"),
        ("https://claude.ai/api/*/auth_callback", "must not wildcard the path"),
    ],
)
def test_redirect_patterns_validated(patterns: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _oauth_config(allowed_redirect_uris=patterns)


def test_redirect_patterns_accept_loopback_forms() -> None:
    cfg = _oauth_config(
        allowed_redirect_uris="http://[::1]:*, http://[::1], http://LOCALHOST:*/cb ,"
        "https://claude.ai/api/mcp/auth_callback"
    )

    assert cfg.allowed_redirect_uri_list == [
        "http://[::1]:*",
        "http://[::1]",
        "http://LOCALHOST:*/cb",
        "https://claude.ai/api/mcp/auth_callback",
    ]


def test_default_redirect_allowlist() -> None:
    assert _oauth_config().allowed_redirect_uri_list == list(DEFAULT_ALLOWED_REDIRECT_URIS)


def test_signing_key_does_not_depend_on_client_secret() -> None:
    first = _provider(client_secret="secret-one")
    rotated = _provider(client_secret="secret-two")

    assert first._jwt_signing_key == rotated._jwt_signing_key


async def test_durable_storage_persists_and_rotates(tmp_path: Path) -> None:
    store = durable_client_storage(tmp_path, SIGNING_KEY)
    await store.put(key="client-1", value={"client_id": "client-1"}, collection="clients")

    reopened = durable_client_storage(tmp_path, SIGNING_KEY)
    assert await reopened.get(key="client-1", collection="clients") == {"client_id": "client-1"}

    rotated = durable_client_storage(tmp_path, "rotated_signing_key_0123456789abcdef")
    assert await rotated.get(key="client-1", collection="clients") is None

    directory = tmp_path / "oauth-proxy"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    stored = b"".join(p.read_bytes() for p in directory.rglob("*") if p.is_file())
    assert b'client-1"}' not in stored


def test_http_server_uses_durable_storage_by_default(fake_env: None, tmp_path: Path) -> None:
    from nz_openbank_mcp.server import build_http_server

    build_http_server(McpHttpConfig(auth_mode="oauth"), _oauth_config(state_dir=str(tmp_path)))

    assert (tmp_path / "oauth-proxy").is_dir()


def test_consent_screen_stays_on() -> None:
    assert _provider()._require_authorization_consent is True


def _google_transport(userinfo: dict[str, object]) -> Any:
    import httpx2

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx2.Response(
                200,
                json={
                    "aud": "google-client",
                    "sub": "1234",
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email "
                    "https://www.googleapis.com/auth/userinfo.profile",
                    "expires_in": 3600,
                    "email": userinfo["email"],
                    "email_verified": "true",
                },
            )
        return httpx2.Response(200, json=userinfo)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.mark.parametrize(
    ("userinfo", "allowed"),
    [
        ({"email": "staff@example.org", "verified_email": True, "hd": "example.org"}, True),
        ({"email": "staff@example.org", "verified_email": True}, False),
        ({"email": "owner@example.com", "verified_email": True}, True),
    ],
)
async def test_google_verifier_claims_drive_allowlist(
    userinfo: dict[str, object], allowed: bool
) -> None:
    provider = _provider()
    client = _google_transport(userinfo)
    provider._token_validator._http_client = client  # type: ignore[attr-defined]
    try:
        access = await provider._token_validator.verify_token("upstream-token")
    finally:
        await client.aclose()

    assert access is not None
    assert provider._is_access_allowed(access) is allowed


def test_http_server_storage_is_encrypted_file_store(fake_env: None, tmp_path: Path) -> None:
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    from nz_openbank_mcp.server import build_http_server

    mcp = build_http_server(
        McpHttpConfig(auth_mode="oauth"), _oauth_config(state_dir=str(tmp_path))
    )

    assert isinstance(mcp.auth._client_storage, FernetEncryptionWrapper)  # type: ignore[union-attr]


def test_registrations_survive_restart_encrypted(fake_env: None, tmp_path: Path) -> None:
    import asyncio
    import json

    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    oauth = _oauth_config(state_dir=str(tmp_path))
    app = build_http_server(cfg, oauth).http_app(path=cfg.path, transport="streamable-http")
    with TestClient(app) as client:
        response = client.post(
            "/register",
            json={
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
    client_id = response.json()["client_id"]

    restarted = build_http_server(cfg, oauth)
    found = asyncio.run(restarted.auth.get_client(client_id))  # type: ignore[union-attr]
    assert found is not None

    files = [p for p in (tmp_path / "oauth-proxy").rglob("*.json") if "info" not in p.name]
    assert files
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert set(json.loads(path.read_text())["value"]) == {
            "__encrypted_data__",
            "__encryption_version__",
        }


def test_signing_key_whitespace_is_ignored(fake_env: None) -> None:
    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(auth_mode="oauth")
    plain = build_http_server(cfg, _oauth_config(), oauth_client_storage=MemoryStore())
    padded = build_http_server(
        cfg, _oauth_config(jwt_signing_key=f"  {SIGNING_KEY}\n"), oauth_client_storage=MemoryStore()
    )

    assert plain.auth._jwt_signing_key == padded.auth._jwt_signing_key  # type: ignore[union-attr]


def test_unwritable_state_dir_names_the_setting(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")

    with pytest.raises(ValueError, match="NZ_OPENBANK_MCP_STATE_DIR is not writable"):
        durable_client_storage(blocker, SIGNING_KEY)
