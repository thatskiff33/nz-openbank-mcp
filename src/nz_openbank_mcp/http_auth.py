"""Inbound authentication for Streamable HTTP MCP deployments."""

from __future__ import annotations

import hmac
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken as FastMCPAccessToken
from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.google import GoogleProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.provider import AccessToken as McpAccessToken
from mcp.server.auth.provider import AuthorizationCode, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import SecretStr
from starlette.routing import Route

GOOGLE_OAUTH_SCOPES = ["openid", "email", "profile"]


class StaticBearerAuthProvider(AuthProvider):
    """Authenticate HTTP MCP requests against one configured bearer token."""

    def __init__(self, bearer_token: SecretStr) -> None:
        super().__init__()
        self._expected = bearer_token.get_secret_value().encode("utf-8")

    async def verify_token(self, token: str) -> FastMCPAccessToken | None:
        """Return access metadata only when the supplied bearer token matches.

        Compares UTF-8 bytes: hmac.compare_digest raises on non-ASCII str.
        """
        supplied = token.encode("utf-8", errors="surrogatepass")
        if hmac.compare_digest(supplied, self._expected):
            return FastMCPAccessToken(
                token=token,
                client_id="nz-openbank-mcp-http",
                scopes=[],
            )
        return None


def durable_client_storage(state_dir: Path, signing_key: str) -> AsyncKeyValue:
    """Encrypted on-disk store for OAuth client registrations and upstream tokens.

    Rotating the signing key makes existing entries undecryptable; they are read
    as misses, so clients re-register instead of the server failing.
    """
    directory = state_dir / "oauth-proxy"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
    )
    encryption_key = derive_jwt_key(
        low_entropy_material=signing_key, salt="nz-openbank-mcp-oauth-storage"
    )
    return FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


class AllowlistedGoogleOAuthProvider(GoogleProvider):
    """Google OAuth proxy that only accepts verified allowlisted accounts.

    Email entries match the verified email exactly. Domain entries match only
    Google's hosted-domain (hd) claim, so a consumer account registered on an
    address at an allowed domain is refused.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str,
        allowed_users: Iterable[str],
        allowed_domains: Iterable[str],
        jwt_signing_key: str,
        allowed_redirect_uris: list[str],
        client_storage: AsyncKeyValue,
    ) -> None:
        self._allowed_users = frozenset(_normalise_email(value) for value in allowed_users)
        self._allowed_domains = frozenset(_normalise_domain(value) for value in allowed_domains)
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            resource_base_url=base_url,
            issuer_url=base_url,
            required_scopes=GOOGLE_OAUTH_SCOPES,
            valid_scopes=GOOGLE_OAUTH_SCOPES,
            allowed_client_redirect_uris=allowed_redirect_uris,
            client_storage=client_storage,
            jwt_signing_key=jwt_signing_key,
        )

    async def load_access_token(self, token: str) -> FastMCPAccessToken | None:
        """Return FastMCP-issued access only for an allowlisted Google email."""
        access = cast(
            FastMCPAccessToken | None,
            await super().load_access_token(token),
        )
        if access is None:
            return None
        if self._is_access_allowed(access):
            return access
        return None

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Issue connector tokens only when the Google account is allowlisted."""
        oauth_token = await super().exchange_authorization_code(client, authorization_code)
        if await self.load_access_token(oauth_token.access_token) is None:
            raise TokenError("invalid_grant", "Google account is not allowed")
        return oauth_token

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Expose the path-aware authorization-server metadata alias."""
        routes = super().get_routes(mcp_path)
        issuer_path = urlparse(str(self.issuer_url)).path.rstrip("/")
        alias_path = f"/.well-known/oauth-authorization-server{issuer_path}"
        if issuer_path and not any(route.path == alias_path for route in routes):
            for route in routes:
                if route.path == "/.well-known/oauth-authorization-server":
                    routes.append(
                        Route(
                            path=alias_path,
                            endpoint=route.endpoint,
                            methods=route.methods,
                            name=route.name,
                            include_in_schema=route.include_in_schema,
                        )
                    )
                    break
        return routes

    def _is_access_allowed(self, access: McpAccessToken) -> bool:
        claims = _access_claims(access)
        email_claim = claims.get("email")
        if not isinstance(email_claim, str):
            return False
        if not _claim_is_true(claims.get("email_verified")):
            return False

        if _normalise_email(email_claim) in self._allowed_users:
            return True
        hosted_domain = _hosted_domain(claims)
        return hosted_domain is not None and hosted_domain in self._allowed_domains


def _normalise_email(value: str) -> str:
    """Normalize Google email claims for allowlist comparison."""
    return value.strip().lower()


def _normalise_domain(value: str) -> str:
    """Normalize Google hosted-domain allowlist entries."""
    return value.strip().lower().removeprefix("@")


def _hosted_domain(claims: Mapping[str, object]) -> str | None:
    """Google Workspace domain from the userinfo response, if the account has one."""
    user_data = claims.get("google_user_data")
    if not isinstance(user_data, Mapping):
        return None
    hd = user_data.get("hd")
    if not isinstance(hd, str) or not hd.strip():
        return None
    return _normalise_domain(hd)


def _claim_is_true(value: object) -> bool:
    """Google tokeninfo may return boolean-like values as strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


def _access_claims(access: McpAccessToken) -> Mapping[str, object]:
    """Return FastMCP token claims when present on the SDK access token."""
    claims = getattr(access, "claims", {})
    if isinstance(claims, Mapping):
        return claims
    return {}
