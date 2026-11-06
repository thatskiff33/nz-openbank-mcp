"""Identity sub-server: 1 read tool + 1 write tool.

Exposes only the user-scoped Akahu identity endpoints. App-scoped endpoints
(`/categories`, `/parties`, `/connections`, `/identity/{id}/verify-name`) are
not reachable from a Personal App and are not shipped.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from nz_openbank_mcp import deps
from nz_openbank_mcp.client import check_akahu_id
from nz_openbank_mcp.safety import describe_request, require_write_consent
from nz_openbank_mcp.tool_metadata import (
    OPEN_WORLD_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
)

# Mount namespace; exposed tool names are `id_<function>`.
NAMESPACE = "id"
server: FastMCP[Any] = FastMCP("identity")


@server.tool(title="Get Me", annotations=READ_ONLY_ANNOTATIONS)
async def get_me() -> dict[str, Any]:
    """Return identity/profile data for the connected Akahu user.

    Returns {"id": str, "email": str | None, "name": str | None}, where name
    joins the profile's first_name and last_name when present.
    """
    me = await deps.get_client().get_me()
    name: str | None = None
    if me.profile and (me.profile.first_name or me.profile.last_name):
        name = " ".join(p for p in (me.profile.first_name, me.profile.last_name) if p)
    return {
        "id": me.id,
        "email": me.email,
        "name": name,
    }


async def _check_name_args(_ctx: Any, kw: dict[str, Any]) -> None:
    if not (kw.get("family_name") or "").strip():
        raise ToolError("family_name must not be blank.")
    if kw.get("account_id") is not None:
        if not kw["account_id"].strip():
            raise ToolError("account_id must not be blank; omit it to check every source.")
        check_akahu_id(kw["account_id"], name="account_id")


def _describe_check(kw: dict[str, Any]) -> str:
    scope = "one account" if kw.get("account_id") is not None else "every connected source"
    return describe_request(
        f"Send this name to Akahu to check against the holder of {scope}. "
        "This sends an identity check to your bank and may incur a per-call charge.",
        [
            ("family name", kw.get("family_name")),
            ("given name", kw.get("given_name")),
            ("middle name", kw.get("middle_name")),
            ("initials", kw.get("initials")),
            ("account", kw.get("account_id")),
        ],
    )


@server.tool(
    title="Verify Name",
    annotations=OPEN_WORLD_WRITE_ANNOTATIONS,
)
@require_write_consent(
    _describe_check, namespace=NAMESPACE, automatable=False, prepare=_check_name_args
)
async def verify_name(
    *,
    ctx: Context,
    family_name: str,
    given_name: str | None = None,
    middle_name: str | None = None,
    initials: list[str] | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Verify a name against the account holder via Akahu's identity check.

    If account_id is provided, the check is scoped to that one account
    (POST /verify/name/{account_id}); otherwise Akahu matches against every
    identity source the user has connected (POST /verify/name).

    Requires the appropriate Personal-App scope grant in your Akahu portal;
    without it Akahu returns 403 Forbidden. May incur a per-call charge from
    your bank. Always elicits user confirmation (not bypass-eligible).

    Returns {"success": bool, "item": dict | None, "message": str | None}
    where item is Akahu's match-result envelope (shape documented at
    https://developers.akahu.nz/docs/enduring-verify-name).

    Args:
        family_name: Required. Surname to verify.
        given_name: Optional first name.
        middle_name: Optional middle name.
        initials: Optional list of initial strings (e.g. ["J", "R"]).
        account_id: Optional account scope; omit to check all sources.
    """
    result = await deps.get_client().verify_name(
        family_name=family_name,
        given_name=given_name,
        middle_name=middle_name,
        initials=initials,
        account_id=account_id,
    )
    return {
        "success": result.success,
        "item": result.item,
        "message": result.message,
    }
