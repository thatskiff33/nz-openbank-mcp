"""Config hardening: no implicit .env, pinned Akahu host, secret handling."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from nz_openbank_mcp.config import AkahuConfig, McpHttpConfig, McpOAuthConfig
from tests.conftest import STATE_DIR

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
    env_file.chmod(0o600)
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
    env_file.chmod(0o600)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    assert AkahuConfig().app_token.get_secret_value() == "app_token_test"


def test_env_file_cannot_opt_in_to_custom_base_url(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text(HOSTILE_DOTENV)
    env_file.chmod(0o600)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    with pytest.raises(
        ValidationError, match=re.escape("base_url must be on https://api.akahu.io")
    ):
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
        "NZ_OPENBANK_MCP_JWT_SIGNING_KEY=jwt_signing_key_test_0123456789abcdef\n"
        f"NZ_OPENBANK_MCP_STATE_DIR={STATE_DIR}\n"
    )
    env_file.chmod(0o600)
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
    monkeypatch.setattr(server, "build_http_server", lambda *_: fake_server)
    monkeypatch.setattr(server, "configure_logging", lambda level: None)
    caplog.set_level(logging.DEBUG)

    server.http_main()

    text = caplog.text
    for secret in ("app_token_test", "user_token_test", "bearer_secret_0123456789abcdef0123"):
        assert secret not in text


def test_bearer_token_minimum_length(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    token = "abcdefghijklmnopqrstuvwxyz012345"
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", token[:31])

    with pytest.raises(ValidationError, match="at least 32 characters"):
        McpHttpConfig()

    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", token)
    assert McpHttpConfig().bearer_token.get_secret_value() == token


@pytest.mark.parametrize("token", ["x" * 48, "abcd" * 12, "123456789" * 5])
def test_low_entropy_bearer_token_is_rejected(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", token)

    with pytest.raises(ValidationError, match="low-entropy"):
        McpHttpConfig()


def test_hex_bearer_token_is_accepted(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    token = "0123456789abcdef" * 4
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", token)

    assert McpHttpConfig().bearer_token.get_secret_value() == token


def test_short_bearer_token_allowed_in_oauth_mode(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NZ_OPENBANK_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "short")

    assert McpHttpConfig().auth_mode == "oauth"


async def test_bearer_provider_compares_bytes() -> None:
    from nz_openbank_mcp.http_auth import StaticBearerAuthProvider

    provider = StaticBearerAuthProvider(SecretStr("tok_" + "a" * 32))

    assert await provider.verify_token("tok_" + "a" * 32) is not None
    assert await provider.verify_token("tök_" + "a" * 32) is None
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


def test_validation_errors_do_not_echo_tokens(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AKAHU_APP_TOKEN", "app_SECRET_value_0123456789")
    monkeypatch.setenv("AKAHU_READ_ONLY", "true")
    monkeypatch.setenv("AKAHU_AUTOMATION_BYPASS", "true")
    with pytest.raises(ValidationError) as bypass_exc:
        AkahuConfig()

    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "SECRET_short")
    with pytest.raises(ValidationError) as bearer_exc:
        McpHttpConfig()

    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "SECRET_GOOGLE")
    monkeypatch.delenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENBANK_MCP_GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(ValidationError) as oauth_exc:
        McpOAuthConfig()

    for exc in (bypass_exc, bearer_exc, oauth_exc):
        assert "SECRET" not in str(exc.value)


def test_fastmcp_settings_ignore_working_directory_dotenv(tmp_path: Path) -> None:
    import subprocess
    import sys

    (tmp_path / ".env").write_text("FASTMCP_LOG_LEVEL=CRITICAL\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("FASTMCP_")}
    probe = "import nz_openbank_mcp, fastmcp; print(fastmcp.settings.log_level)"

    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert out.stdout.strip() == "INFO"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_env_file_writable_by_others_is_refused(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text("AKAHU_READ_ONLY=false\n")
    env_file.chmod(0o666)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))

    with pytest.raises(ValueError, match="must not be writable by group or others"):
        AkahuConfig()


def test_env_file_mode_not_checked_off_posix(
    plugin_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nz_openbank_mcp import config

    env_file = tmp_path / "server.env"
    env_file.write_text("AKAHU_READ_ONLY=false\n")
    env_file.chmod(0o666)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))
    monkeypatch.setattr(config.sys, "platform", "win32")

    assert config.explicit_env_file() == env_file


def test_working_directory_dotenv_ignored_by_http_and_oauth_settings(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for var in ("NZ_OPENBANK_MCP_HTTP_HOST", "OPENBANK_MCP_HTTP_HOST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", "process_bearer_0123456789abcdef0123")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("NZ_OPENBANK_MCP_GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("NZ_OPENBANK_MCP_PUBLIC_BASE_URL", "https://mcp.example.com/openbank-mcp")
    monkeypatch.setenv("NZ_OPENBANK_MCP_ALLOWED_USERS", "owner@example.com")
    monkeypatch.delenv("NZ_OPENBANK_MCP_ALLOWED_DOMAINS", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_JWT_SIGNING_KEY", "jwt_signing_key_test_0123456789abcdef")
    monkeypatch.setenv("NZ_OPENBANK_MCP_STATE_DIR", STATE_DIR)
    (tmp_path / ".env").write_text(
        "NZ_OPENBANK_MCP_HTTP_HOST=0.0.0.0\nNZ_OPENBANK_MCP_ALLOWED_DOMAINS=attacker.example\n"
    )
    monkeypatch.chdir(tmp_path)

    assert McpHttpConfig().host == "127.0.0.1"
    assert McpOAuthConfig().allowed_domain_set == frozenset()


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://api.akahu.io\t/v1", "whitespace or control"),
        ("https://api.akahu.io/v 1", "whitespace or control"),
        ("https://api.akahu.io/v1\x00", "whitespace or control"),
        ("https://api.akahu.io/v1?", "query string"),
        ("https://api.akahu.io/v1?x=1", "query string"),
        ("https://api.akahu.io/v1#", "fragment"),
    ],
)
def test_base_url_rejects_ambiguous_characters(fake_env: None, url: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AkahuConfig(base_url=url)


def test_base_url_surrounding_whitespace_is_stripped(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AKAHU_BASE_URL", "  https://api.akahu.io/v1\n")

    assert AkahuConfig().base_url == "https://api.akahu.io/v1"


@pytest.mark.parametrize("token", ["tök_" + "a" * 32, "a" * 16 + " " + "a" * 16])
def test_bearer_token_must_be_visible_ascii(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.delenv("OPENBANK_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("NZ_OPENBANK_MCP_BEARER_TOKEN", token)

    with pytest.raises(ValidationError, match="visible ASCII"):
        McpHttpConfig()


@pytest.mark.parametrize("header", [b"Bearer \xff\xfe", "Bearer ünïcödé".encode()])
def test_http_non_ascii_bearer_header_returns_401(fake_env: None, header: bytes) -> None:
    from starlette.testclient import TestClient

    from nz_openbank_mcp.server import build_http_server

    cfg = McpHttpConfig(bearer_token=SecretStr("bearer_0123456789abcdefghijklmnopq"))
    app = build_http_server(cfg).http_app(path=cfg.path, transport="streamable-http")

    with TestClient(app) as client:
        response = client.post(cfg.path, json={}, headers={"Authorization": header})  # type: ignore[dict-item]

    assert response.status_code == 401


def test_banner_warns_when_base_url_is_custom(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_openbank_mcp.server import log_startup_banner

    monkeypatch.setenv("AKAHU_ALLOW_CUSTOM_BASE_URL", "true")
    monkeypatch.setenv("AKAHU_BASE_URL", "https://akahu-mock.example/v1")
    caplog.set_level(logging.INFO)

    log_startup_banner()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("akahu-mock.example" in r.getMessage() for r in warnings)
    assert "app_token_test" not in caplog.text


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_env_file_owned_by_another_user_is_refused(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nz_openbank_mcp import config

    env_file = tmp_path / "server.env"
    env_file.write_text("AKAHU_READ_ONLY=false\n")
    env_file.chmod(0o600)
    monkeypatch.setenv("AKAHU_ENV_FILE", str(env_file))
    owner = env_file.stat().st_uid
    monkeypatch.setattr(config.os, "getuid", lambda: owner + 1)

    with pytest.raises(ValueError, match="owned by root or the current user"):
        config.explicit_env_file()
