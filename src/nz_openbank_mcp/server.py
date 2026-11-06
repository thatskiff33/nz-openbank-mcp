"""Root FastMCP server. Mounts sub-servers and runs over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from key_value.aio.protocols import AsyncKeyValue

from nz_openbank_mcp import deps
from nz_openbank_mcp.config import AKAHU_API_HOST, McpHttpConfig, McpOAuthConfig, get_config
from nz_openbank_mcp.http_auth import (
    AllowlistedGoogleOAuthProvider,
    DurableOAuthStorage,
    StaticBearerAuthProvider,
    durable_client_storage,
)
from nz_openbank_mcp.safety import bypass_eligible_tools
from nz_openbank_mcp.tools import accounts, identity, transactions

logger = logging.getLogger(__name__)
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_SENSITIVE_THIRD_PARTY_LOGGERS = ("httpx", "httpcore", "httpx2", "httpcore2", "uvicorn.access")

SERVER_INSTRUCTIONS = (
    "Use Akahu tools only for the connected user's New Zealand banking data. "
    "For last-month transactions, call txn_get_transactions with explicit "
    "start_date and end_date values. Prefer read tools. Write tools refresh "
    "data or send support/identity requests and are guarded by read-only mode "
    "and consent."
)


STATE_CULL_INTERVAL_SECONDS = 3600.0


async def _cull_periodically(state: DurableOAuthStorage) -> None:
    while True:
        try:
            await state.cull()
        except Exception:
            # One failed sweep must not take the server down; the next one retries.
            logger.warning("OAuth state cull failed", exc_info=True)
        await asyncio.sleep(STATE_CULL_INTERVAL_SECONDS)


def _lifespan(
    oauth_state: DurableOAuthStorage | None,
) -> Callable[[FastMCP[Any]], AbstractAsyncContextManager[dict[str, Any]]]:
    @asynccontextmanager
    async def lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
        culler = asyncio.create_task(_cull_periodically(oauth_state)) if oauth_state else None
        try:
            yield {}
        finally:
            if culler is not None:
                culler.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await culler
            await deps.aclose_client()

    return lifespan


def build_server(
    *,
    auth: AuthProvider | None = None,
    oauth_state: DurableOAuthStorage | None = None,
) -> FastMCP[Any]:
    """Construct the root FastMCP server with all sub-servers mounted.

    oauth_state, if given, is culled of expired entries at startup and hourly.
    """
    mcp: FastMCP[Any] = FastMCP(
        "nz-openbank-mcp",
        instructions=SERVER_INSTRUCTIONS,
        auth=auth,
        lifespan=_lifespan(oauth_state),
    )
    mcp.mount(accounts.server, namespace=accounts.NAMESPACE)
    mcp.mount(transactions.server, namespace=transactions.NAMESPACE)
    mcp.mount(identity.server, namespace=identity.NAMESPACE)
    return mcp


def build_http_server(
    http_cfg: McpHttpConfig,
    oauth_cfg: McpOAuthConfig | None = None,
    oauth_client_storage: AsyncKeyValue | None = None,
) -> FastMCP[Any]:
    """Construct the root server with configured inbound HTTP auth."""
    if http_cfg.auth_mode == "oauth":
        if oauth_cfg is None:
            oauth_cfg = McpOAuthConfig()
        signing_key = oauth_cfg.jwt_signing_key.get_secret_value().strip()
        if oauth_client_storage is None:
            oauth_client_storage = durable_client_storage(Path(oauth_cfg.state_dir), signing_key)
        auth: AuthProvider = AllowlistedGoogleOAuthProvider(
            client_id=oauth_cfg.google_client_id,
            client_secret=oauth_cfg.google_client_secret.get_secret_value(),
            base_url=oauth_cfg.public_base_url,
            allowed_users=oauth_cfg.allowed_user_set,
            allowed_domains=oauth_cfg.allowed_domain_set,
            jwt_signing_key=signing_key,
            allowed_redirect_uris=oauth_cfg.allowed_redirect_uri_list,
            client_storage=oauth_client_storage,
        )
        state = (
            oauth_client_storage if isinstance(oauth_client_storage, DurableOAuthStorage) else None
        )
        return build_server(auth=auth, oauth_state=state)
    return build_server(auth=StaticBearerAuthProvider(http_cfg.bearer_token))


def http_guard_options(http_cfg: McpHttpConfig, oauth_cfg: McpOAuthConfig | None) -> dict[str, Any]:
    """Host and Origin validation for the HTTP app.

    Loopback is always accepted (FastMCP's defaults). Configured hosts and, in
    OAuth mode, the public base URL's host are added, each with its https
    origin, since a TLS proxy forwards plain http and a same-origin check
    would not match.
    """
    public = [urlsplit(oauth_cfg.public_base_url).netloc.lower()] if oauth_cfg else []
    hosts = list(dict.fromkeys([*http_cfg.allowed_host_list, *public]))
    return {
        "host_origin_protection": True,
        "allowed_hosts": hosts,
        "allowed_origins": [f"https://{host}" for host in hosts],
    }


def log_startup_banner() -> None:
    """Emit a banner describing the current safety posture."""
    cfg = get_config()
    host = urlsplit(cfg.base_url).hostname
    if host != AKAHU_API_HOST:
        logger.warning(
            "AKAHU_BASE_URL points at %s, not %s. Akahu tokens are sent to that host.",
            host,
            AKAHU_API_HOST,
        )
    if cfg.read_only:
        logger.info(
            "nz-openbank-mcp starting in READ-ONLY mode. All write tools will refuse "
            "until AKAHU_READ_ONLY=false."
        )
        return
    if cfg.automation_bypass:
        eligible = bypass_eligible_tools()
        logger.warning(
            "Automation bypass ENABLED. The following tools will skip the "
            "confirmation prompt: %s. All other writes still require "
            "confirmation. Disable by setting AKAHU_AUTOMATION_BYPASS=false.",
            ", ".join(eligible),
        )
        return
    logger.info(
        "nz-openbank-mcp starting in WRITE mode. All writes require confirmation "
        "in your MCP client."
    )


def configure_logging(log_level: str) -> None:
    """Configure application logging without leaking bearer tokens from HTTP clients."""
    logging.basicConfig(level=log_level, format=_LOG_FORMAT)
    for logger_name in _SENSITIVE_THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def main() -> None:
    """Entry point used by the `nz-openbank-mcp` console script."""
    configure_logging(get_config().log_level)
    log_startup_banner()
    build_server().run(show_banner=False)


def http_main() -> None:
    """Entry point used by the `nz-openbank-mcp-http` console script."""
    akahu_cfg = get_config()
    http_cfg = McpHttpConfig()
    oauth_cfg = McpOAuthConfig() if http_cfg.auth_mode == "oauth" else None
    configure_logging(akahu_cfg.log_level)
    log_startup_banner()
    guard = http_guard_options(http_cfg, oauth_cfg)
    logger.info(
        "nz-openbank-mcp HTTP starting on %s:%s%s with %s auth; Host accepted: loopback%s",
        http_cfg.host,
        http_cfg.port,
        http_cfg.path,
        http_cfg.auth_mode,
        "".join(f", {host}" for host in guard["allowed_hosts"]),
    )
    if not guard["allowed_hosts"]:
        logger.warning(
            "Only loopback Host headers are accepted. Behind a reverse proxy, set "
            "NZ_OPENBANK_MCP_ALLOWED_HOSTS to the public host name or requests get HTTP 421."
        )
    build_http_server(http_cfg, oauth_cfg).run(
        transport="streamable-http",
        show_banner=False,
        host=http_cfg.host,
        port=http_cfg.port,
        path=http_cfg.path,
        uvicorn_config={"access_log": False},
        **guard,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
