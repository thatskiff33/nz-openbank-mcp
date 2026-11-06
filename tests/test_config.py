"""Tests for AkahuConfig: env loading, validation, auth headers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest import STATE_DIR

BEARER = "http_token_test_0123456789abcdef0123"

OAUTH_ENV_VARS = (
    "NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID",
    "OPENBANK_MCP_GOOGLE_CLIENT_ID",
    "NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET",
    "OPENBANK_MCP_GOOGLE_CLIENT_SECRET",
    "NZ_OPENBANK_MCP_PUBLIC_BASE_URL",
    "OPENBANK_MCP_PUBLIC_BASE_URL",
    "NZ_OPENBANK_MCP_ALLOWED_USERS",
    "OPENBANK_MCP_ALLOWED_USERS",
    "NZ_OPENBANK_MCP_ALLOWED_DOMAINS",
    "OPENBANK_MCP_ALLOWED_DOMAINS",
    "NZ_OPENBANK_MCP_JWT_SIGNING_KEY",
    "OPENBANK_MCP_JWT_SIGNING_KEY",
    "NZ_OPENBANK_MCP_STATE_DIR",
    "OPENBANK_MCP_STATE_DIR",
    "NZ_OPENBANK_MCP_ALLOWED_REDIRECT_URIS",
    "OPENBANK_MCP_ALLOWED_REDIRECT_URIS",
)
SIGNING_KEY = "jwt_signing_key_test_0123456789abcdef"


@pytest.fixture
def clean_oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove OAuth env vars that could be present on a developer host.

    Signing key and state dir are set so each test varies only what it covers.
    """
    for key in OAUTH_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_JWT_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("NZ_OPENBANK_MCP_STATE_DIR", STATE_DIR)


def test_loads_from_env(fake_env: None) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.app_token.get_secret_value() == "app_token_test"
    assert cfg.user_token.get_secret_value() == "user_token_test"
    assert cfg.base_url == "https://api.akahu.io/v1"
    assert cfg.read_only is True
    assert cfg.automation_bypass is False
    assert cfg.request_timeout == 5
    assert cfg.log_level == "INFO"


def test_base_url_trailing_slash_is_normalised(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_BASE_URL", "https://api.akahu.io/v1/")
    assert AkahuConfig().base_url == "https://api.akahu.io/v1"


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("http://api.akahu.io/v1", "https"),
        ("https:///v1", "host"),
        ("https://api.akahu.io/v1?debug=true", "query"),
        ("https://api.akahu.io/v1#frag", "fragment"),
    ],
)
def test_rejects_unsafe_base_urls(
    monkeypatch: pytest.MonkeyPatch, fake_env: None, base_url: str, message: str
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_BASE_URL", base_url)
    with pytest.raises(ValidationError, match=message):
        AkahuConfig()


def test_is_configured_true_when_both_tokens_present(fake_env: None) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    assert AkahuConfig().is_configured is True


def test_is_configured_false_when_app_token_missing(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_APP_TOKEN", "")
    assert AkahuConfig().is_configured is False


def test_is_configured_false_when_user_token_missing(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_USER_TOKEN", "")
    assert AkahuConfig().is_configured is False


def test_auth_headers_contain_both_tokens(fake_env: None) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    headers = cfg.auth_headers
    assert headers["Authorization"] == "Bearer user_token_test"
    assert headers["X-Akahu-Id"] == "app_token_test"


def test_bypass_with_read_only_raises(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    """Incoherent combination must fail loudly at startup, not silently ignore."""
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_READ_ONLY", "true")
    monkeypatch.setenv("AKAHU_AUTOMATION_BYPASS", "true")
    with pytest.raises(ValidationError) as exc_info:
        AkahuConfig()
    assert "automation_bypass" in str(exc_info.value).lower()


def test_writable_env_loads(writable_env: None) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.read_only is False
    assert cfg.automation_bypass is False


def test_bypass_env_loads(bypass_env: None) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.read_only is False
    assert cfg.automation_bypass is True


def test_http_config_loads_nz_prefixed_env(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", BEARER)
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_PORT", "8091")
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_PATH", "/mcp")

    cfg = McpHttpConfig()
    assert cfg.auth_mode == "bearer"
    assert cfg.bearer_token.get_secret_value() == BEARER
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8091
    assert cfg.path == "/mcp"


def test_http_config_loads_akahu_prefixed_bearer_alias(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.delenv("NZ_OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("OPENBANK_MCP_BEARER_TOKEN", BEARER)

    assert McpHttpConfig().bearer_token.get_secret_value() == BEARER


def test_http_config_oauth_mode_does_not_require_bearer(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.delenv("NZ_OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("OPENBANK_MCP_AUTH_MODE", "OAUTH")

    cfg = McpHttpConfig()
    assert cfg.auth_mode == "oauth"
    assert cfg.bearer_token.get_secret_value() == ""


def test_http_config_ignores_unprefixed_process_path(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.setenv("PATH", "/not/the/mcp/path")
    monkeypatch.setenv("OPENBANK_MCP_AUTH_MODE", "oauth")

    assert McpHttpConfig().path == "/mcp"


def test_http_config_rejects_non_string_auth_mode(fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    with pytest.raises(ValidationError, match="auth_mode"):
        McpHttpConfig(auth_mode=b"oauth")


def test_http_config_requires_bearer_token(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.delenv("NZ_OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="bearer token"):
        McpHttpConfig()


def test_http_config_rejects_relative_path(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    from nz_openbank_mcp.config import McpHttpConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", BEARER)
    monkeypatch.setenv("NZ_OPENBANK_MCP_HTTP_PATH", "mcp")

    with pytest.raises(ValidationError, match="http path"):
        McpHttpConfig()


def test_oauth_config_loads_nz_prefixed_env(
    monkeypatch: pytest.MonkeyPatch, clean_oauth_env: None
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv(
        "NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID",
        "google-client.apps.googleusercontent.com",
    )
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv(
        "NZ_OPENBANK_MCP_PUBLIC_BASE_URL",
        "https://mcp.example.com/openbank-mcp/",
    )
    monkeypatch.setenv(
        "NZ_OPENBANK_MCP_ALLOWED_USERS",
        " Owner@example.com , Other@example.com ",
    )
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_DOMAINS", " Example.ORG , @Example.NET ")

    cfg = McpOAuthConfig()

    assert cfg.google_client_id == "google-client.apps.googleusercontent.com"
    assert cfg.google_client_secret.get_secret_value() == "google-secret"
    assert cfg.public_base_url == "https://mcp.example.com/openbank-mcp"
    assert cfg.allowed_user_set == frozenset({"owner@example.com", "other@example.com"})
    assert cfg.allowed_domain_set == frozenset({"example.org", "example.net"})
    assert cfg.google_redirect_uri == "https://mcp.example.com/openbank-mcp/auth/callback"
    assert "google-secret" not in repr(cfg)


def test_oauth_config_loads_akahu_prefixed_aliases(
    monkeypatch: pytest.MonkeyPatch, clean_oauth_env: None
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv("OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("OPENBANK_MCP_PUBLIC_BASE_URL", "https://example.com/akahu")
    monkeypatch.setenv("OPENBANK_MCP_ALLOWED_USERS", "owner@example.com")

    cfg = McpOAuthConfig()
    assert cfg.google_client_id == "google-client"
    assert cfg.allowed_user_set == frozenset({"owner@example.com"})


@pytest.mark.parametrize(
    ("missing_key", "message"),
    [
        ("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "client id"),
        ("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "client secret"),
        ("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", "public base url"),
    ],
)
def test_oauth_config_requires_core_fields(
    monkeypatch: pytest.MonkeyPatch,
    clean_oauth_env: None,
    missing_key: str,
    message: str,
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    values = {
        "NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID": "google-client",
        "NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET": "google-secret",
        "NZ_OPENBANK_MCP_PUBLIC_BASE_URL": "https://mcp.example.com/openbank-mcp",
        "NZ_OPENBANK_MCP_ALLOWED_USERS": "owner@example.com",
    }
    values[missing_key] = ""
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=message):
        McpOAuthConfig()


def test_oauth_config_requires_allowlist(
    monkeypatch: pytest.MonkeyPatch, clean_oauth_env: None
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", "https://mcp.example.com/openbank-mcp")

    with pytest.raises(ValidationError, match="allowlist"):
        McpOAuthConfig()


@pytest.mark.parametrize(
    ("public_base_url", "message"),
    [
        ("http://mcp.example.com/openbank-mcp", "https"),
        ("https:///openbank-mcp", "host"),
        ("https://mcp.example.com/openbank-mcp?debug=true", "query"),
        ("https://mcp.example.com/openbank-mcp#frag", "fragment"),
        ("https://mcp.example.com:0/openbank-mcp", "port must be 1 to 65535: 0"),
        ("https://mcp.example.com:99999/openbank-mcp", "port must be 1 to 65535: 99999"),
        ("https://user@mcp.example.com/openbank-mcp", "plain host or host:port"),
        ("https://mcp.example.com:\uff18\uff10/openbank-mcp", "plain host or host:port"),
        ("https://mcp.example.com:\u0668\u0660/openbank-mcp", "plain host or host:port"),
    ],
)
def test_oauth_config_rejects_bad_public_base_urls(
    monkeypatch: pytest.MonkeyPatch,
    clean_oauth_env: None,
    public_base_url: str,
    message: str,
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", public_base_url)
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_USERS", "owner@example.com")

    with pytest.raises(ValidationError, match=message):
        McpOAuthConfig()


@pytest.mark.parametrize(
    ("allowed_users", "allowed_domains", "message"),
    [
        ("not-an-email", "", "email addresses"),
        ("", "https://example.com", "bare domains"),
        ("", "@", "bare domains"),
    ],
)
def test_oauth_config_rejects_bad_allowlist_entries(
    monkeypatch: pytest.MonkeyPatch,
    clean_oauth_env: None,
    allowed_users: str,
    allowed_domains: str,
    message: str,
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", "https://mcp.example.com/openbank-mcp")
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_USERS", allowed_users)
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_DOMAINS", allowed_domains)

    with pytest.raises(ValidationError, match=message):
        McpOAuthConfig()


def test_mask_accounts_defaults_off_and_reads_the_environment(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.delenv("AKAHU_MASK_ACCOUNTS", raising=False)
    assert AkahuConfig().mask_accounts is False
    monkeypatch.setenv("AKAHU_MASK_ACCOUNTS", "true")
    assert AkahuConfig().mask_accounts is True


@pytest.mark.parametrize(
    "value",
    ["", "  ", "${user_config.akahu_mask_accounts}", "${AKAHU_MASK_ACCOUNTS:-false}"],
)
def test_mask_accounts_empty_or_unresolved_means_the_default(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """An install from before the setting existed must still start."""
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_MASK_ACCOUNTS", value)
    assert AkahuConfig().mask_accounts is False


def test_mask_accounts_rejects_other_values(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_openbank_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_MASK_ACCOUNTS", "sometimes")
    with pytest.raises(ValidationError, match="mask_accounts"):
        AkahuConfig()


@pytest.mark.parametrize("port", ["1", "8443", "65535"])
def test_oauth_config_accepts_public_base_url_ports_in_range(
    monkeypatch: pytest.MonkeyPatch, clean_oauth_env: None, port: str
) -> None:
    from nz_openbank_mcp.config import McpOAuthConfig

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", f"https://mcp.example.com:{port}/mcp")
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_USERS", "owner@example.com")

    assert McpOAuthConfig().public_base_url == f"https://mcp.example.com:{port}/mcp"
