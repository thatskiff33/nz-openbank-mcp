"""Config hardening: no implicit .env, pinned Akahu host, secret handling."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from nz_openbank_mcp.config import AkahuConfig, McpHttpConfig, McpOAuthConfig

HOSTILE_DOTENV = """\
AKAHU_BASE_URL=https://attacker.example/v1
AKAHU_READ_ONLY=false
AKAHU_AUTOMATION_BYPASS=true
AKAHU_ALLOW_CUSTOM_BASE_URL=true
AKAHU_APP_TOKEN=file_app_token
AKAHU_USER_TOKEN=file_user_token
"""


@pytest.fixture
def plugin_env(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    """Tokens injected the way plugin and Desktop launches do; nothing else set."""
    for var in ("AKAHU_BASE_URL", "AKAHU_READ_ONLY", "AKAHU_AUTOMATION_BYPASS"):
        monkeypatch.delenv(var, raising=False)


def test_working_directory_dotenv_is_ignored(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(HOSTILE_DOTENV)
    monkeypatch.chdir(tmp_path)

    cfg = AkahuConfig()

    assert cfg.base_url == "https://api.akahu.io/v1"
    assert cfg.read_only is True
    assert cfg.automation_bypass is False
    assert cfg.app_token.get_secret_value() == "app_token_test"


async def test_working_directory_dotenv_cannot_redirect_tokens(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nz_openbank_mcp.client import AkahuClient

    (tmp_path / ".env").write_text(HOSTILE_DOTENV)
    monkeypatch.chdir(tmp_path)

    with respx.mock(assert_all_called=False) as router:
        attacker = router.route(host="attacker.example").mock(
            return_value=httpx.Response(200, json={"success": True, "items": []})
        )
        akahu = router.get("https://api.akahu.io/v1/accounts").mock(
            return_value=httpx.Response(200, json={"success": True, "items": []})
        )
        client = AkahuClient(AkahuConfig())
        try:
            await client.list_accounts()
        finally:
            await client.aclose()

    assert attacker.call_count == 0
    assert akahu.call_count == 1
    sent = akahu.calls[0].request.headers
    assert sent["Authorization"] == "Bearer user_token_test"
    assert sent["X-Akahu-Id"] == "app_token_test"


def test_explicit_env_file_is_loaded(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text("AKAHU_READ_ONLY=false\nAKAHU_LOG_LEVEL=debug\n")
    monkeypatch.delenv("AKAHU_LOG_LEVEL")
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    cfg = AkahuConfig()

    assert cfg.read_only is False
    assert cfg.log_level == "DEBUG"


def test_process_environment_wins_over_env_file(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text("AKAHU_APP_TOKEN=file_app_token\n")
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    assert AkahuConfig().app_token.get_secret_value() == "app_token_test"


def test_env_file_cannot_opt_in_to_custom_base_url(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text(HOSTILE_DOTENV)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    with pytest.raises(ValidationError, match="base_url must be on https://api.akahu.io"):
        AkahuConfig()


@pytest.mark.parametrize("value", ["server.env", "./server.env", "~/server.env"])
def test_env_file_must_be_absolute(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("AKAHU_ENV_FILE", value)

    with pytest.raises(ValueError, match="AKAHU_ENV_FILE must be an absolute path"):
        AkahuConfig()


def test_env_file_must_exist(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AKAHU_ENV_FILE", str(tmp_path / "missing.env"))

    with pytest.raises(ValueError, match="does not name a file"):
        AkahuConfig()


def test_env_file_applies_to_http_and_oauth_settings(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for var in ("NZ_OPENBANK_MCP_BEARER_TOKEN", "OPENBANK_MCP_BEARER_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NZ_OPENBANK_MCP_BEARER_TOKEN=file_bearer_token_0123456789abcdef\n"
        "NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID=client-id\n"
        "NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET=client-secret\n"
        "NZ_OPENBANK_MCP_PUBLIC_BASE_URL=https://mcp.example.com/openbank-mcp\n"
        "NZ_OPENBANK_MCP_ALLOWED_USERS=owner@example.com\n"
    )
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    http = McpHttpConfig()
    oauth = McpOAuthConfig()

    assert http.bearer_token.get_secret_value() == "file_bearer_token_0123456789abcdef"
    assert oauth.google_client_id == "client-id"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.akahu.io/v1",
        "https://API.AKAHU.IO/v1/",
        "https://api.akahu.io:443/v1",
    ],
)
def test_akahu_host_accepted(fake_env: None, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("AKAHU_BASE_URL", url)

    assert AkahuConfig().base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/v1",
        "https://api.akahu.io.attacker.example/v1",
        "https://api.akahu.io./v1",
        "https://api.akahu.io:8443/v1",
        "https://akahu.io/v1",
    ],
)
def test_other_hosts_rejected_without_opt_in(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("AKAHU_BASE_URL", url)

    with pytest.raises(ValidationError, match="AKAHU_ALLOW_CUSTOM_BASE_URL=true"):
        AkahuConfig()


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes"])
def test_custom_host_allowed_with_process_env_opt_in(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("AKAHU_ALLOW_CUSTOM_BASE_URL", flag)
    monkeypatch.setenv("AKAHU_BASE_URL", "https://akahu-mock.example/v1")

    assert AkahuConfig().base_url == "https://akahu-mock.example/v1"


@pytest.mark.parametrize("flag", ["", "false", "0", "no"])
def test_custom_host_opt_in_requires_truthy_value(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("AKAHU_ALLOW_CUSTOM_BASE_URL", flag)
    monkeypatch.setenv("AKAHU_BASE_URL", "https://akahu-mock.example/v1")

    with pytest.raises(ValidationError):
        AkahuConfig()


def test_custom_host_still_requires_https(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKAHU_ALLOW_CUSTOM_BASE_URL", "true")
    monkeypatch.setenv("AKAHU_BASE_URL", "http://akahu-mock.example/v1")

    with pytest.raises(ValidationError, match="base_url must use https"):
        AkahuConfig()


def test_base_url_rejects_credentials(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKAHU_BASE_URL", "https://user:pass@api.akahu.io/v1")

    with pytest.raises(ValidationError, match="must not include credentials"):
        AkahuConfig()


def test_reprs_and_dumps_hide_tokens(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "bearer_secret_0123456789abcdef0123")
    akahu = AkahuConfig()
    http = McpHttpConfig()

    blob = " ".join([repr(akahu), str(akahu), repr(http), str(akahu.model_dump()), str(http)])

    for secret in ("app_token_test", "user_token_test", "bearer_secret_0123456789abcdef0123"):
        assert secret not in blob


def test_startup_logs_contain_no_token_material(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp import server

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "bearer_secret_0123456789abcdef0123")
    fake_server = type("S", (), {"run": lambda self, **kwargs: None})()
    monkeypatch.setattr(server, "build_http_server", lambda cfg: fake_server)
    monkeypatch.setattr(server, "configure_logging", lambda level: None)
    caplog.set_level(logging.DEBUG)

    server.http_main()

    text = caplog.text
    for secret in ("app_token_test", "user_token_test", "bearer_secret_0123456789abcdef0123"):
        assert secret not in text


def test_bearer_token_minimum_length(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "x" * 31)

    with pytest.raises(ValidationError, match="at least 32 characters"):
        McpHttpConfig()

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "x" * 32)
    assert McpHttpConfig().bearer_token.get_secret_value() == "x" * 32


def test_short_bearer_token_allowed_in_oauth_mode(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NZ_OPENBANK_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "short")

    assert McpHttpConfig().auth_mode == "oauth"


async def test_bearer_provider_compares_bytes() -> None:
    from nz_openbank_mcp.http_auth import StaticBearerAuthProvider

    provider = StaticBearerAuthProvider(SecretStr("tök_" + "a" * 32))

    assert await provider.verify_token("tök_" + "a" * 32) is not None
    assert await provider.verify_token("tok_" + "a" * 32) is None
    assert await provider.verify_token("ünïcödé") is None
    assert await provider.verify_token("\udcff") is None


@pytest.mark.parametrize(("raw", "expected"), [("debug", "DEBUG"), (" Warning ", "WARNING")])
def test_log_level_is_case_insensitive(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("AKAHU_LOG_LEVEL", raw)

    assert AkahuConfig().log_level == expected


def test_log_level_rejects_unknown(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKAHU_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError, match="log_level"):
        AkahuConfig()


def test_log_level_rejects_non_string(fake_env: None) -> None:
    with pytest.raises(ValidationError, match="log_level"):
        AkahuConfig(log_level=10)  # type: ignore[arg-type]
