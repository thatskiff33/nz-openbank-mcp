"""FastMCP private attributes the OAuth allowlist relies on (CQ-01).

`AllowlistedGoogleOAuthProvider._refuse_unless_allowed` reads the pending
authorization code and validates the upstream Google token through two
private attributes of FastMCP's OAuth proxy. If a FastMCP release renames
them, every sign-in fails; this test names the cause instead.
"""

from __future__ import annotations

from key_value.aio.stores.memory import MemoryStore

from nz_openbank_mcp.config import DEFAULT_ALLOWED_REDIRECT_URIS
from nz_openbank_mcp.http_auth import AllowlistedGoogleOAuthProvider

REQUIRED = {
    "_code_store": ("get", "delete"),
    "_token_validator": ("verify_token",),
}


def _provider() -> AllowlistedGoogleOAuthProvider:
    return AllowlistedGoogleOAuthProvider(
        client_id="google-client",
        client_secret="google-secret",
        base_url="https://mcp.example.com/openbank-mcp",
        allowed_users=["owner@example.com"],
        allowed_domains=[],
        jwt_signing_key="jwt-signing-key-0123456789abcdef0123456789",
        allowed_redirect_uris=list(DEFAULT_ALLOWED_REDIRECT_URIS),
        client_storage=MemoryStore(),
    )


def test_oauth_proxy_still_has_the_private_attributes_we_use() -> None:
    provider = _provider()
    for attribute, methods in REQUIRED.items():
        assert hasattr(provider, attribute), (
            f"FastMCP's OAuth proxy no longer has {attribute}; update "
            "AllowlistedGoogleOAuthProvider._refuse_unless_allowed in http_auth.py"
        )
        for method in methods:
            assert callable(getattr(getattr(provider, attribute), method, None)), (
                f"{attribute}.{method} is missing; update http_auth.py"
            )
