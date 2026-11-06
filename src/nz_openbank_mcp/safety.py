"""Safety layer: read-only refusal, write-consent elicitation, automation bypass.

Three layers protect write operations:
  1. AKAHU_READ_ONLY=true (default) -> raise ReadOnlyError before any HTTP call.
  2. Per-call user confirmation -> raise ElicitationDeclinedError on Decline,
     ElicitationCancelledError (a subclass) on Cancel or no answer.
  3. automation_bypass + automatable=True opts out of (2) for marked tools.

The confirmation text is built from the final arguments, after any missing
values have been collected, and lists every value sent to Akahu. Values are
quoted with control and invisible characters escaped, so model-supplied text
cannot change how the prompt reads; a value too long to show in full is
refused rather than cut short.

Confirmation uses ctx.elicit() on handshake-era connections. On 2026-07-28
connections, which have no server-initiated requests, the tool instead returns
an InputRequiredResult and proceeds only when the client retries with an
accept answer and the single-use nonce issued for that ask. The SDK seals
request_state and binds it to the tool name and arguments, so a nonce cannot
be forged or replayed against a different call. The nonce is also tied to the
exact prompt text, so a retry that would send anything other than what the
user approved is asked again.

`bypass_eligible_tools()` returns the exposed names (`<namespace>_<function>`)
of tools registered with automatable=True.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    get_elicitation_schema,
)
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

from nz_openbank_mcp.config import get_config

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_BYPASS_REGISTRY: set[str] = set()

_CONSENT_KEY = "consent"
_STATE_PREFIX = "consent:"
# Matches the SDK's default request_state lifetime.
_PENDING_TTL_SECONDS = 600.0
# Bounds memory if a client asks repeatedly without ever answering.
_PENDING_MAX = 256
_PENDING: dict[str, tuple[float, str]] = {}

MAX_SHOWN_CHARS = 1000
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_HIDDEN_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
_BMP_MAX = 0xFFFF

Describe = str | Callable[[dict[str, Any]], str]
Prepare = Callable[[Any, dict[str, Any]], Awaitable[None]]


class MissingCredentialsError(ToolError):
    """Raised when AKAHU_APP_TOKEN or AKAHU_USER_TOKEN is unset."""


class ReadOnlyError(ToolError):
    """Raised when a write tool is invoked while AKAHU_READ_ONLY=true."""


class ElicitationDeclinedError(ToolError):
    """Raised when the user declines a write elicitation.

    Also the base class for ElicitationCancelledError, so `except
    ElicitationDeclinedError` catches both decline and cancel outcomes.
    """


class ElicitationCancelledError(ElicitationDeclinedError):
    """Raised when the user cancels (rather than explicitly declines).

    Subclass of ElicitationDeclinedError so binary "did the user consent?"
    handlers keep working while audit/log paths can distinguish the actions.
    """


class _Confirmation(BaseModel):
    """Empty schema for confirmation-only elicitations.

    Replaces the deprecated response_type=None form, which causes some
    clients (e.g. VS Code) to render an empty, non-functional form. With
    this empty model the client shows only the message and accept/
    decline/cancel actions.
    """


def shown(value: str) -> str:
    """`value` as one double-quoted literal, safe to place in a consent prompt."""
    if not isinstance(value, str):
        raise ToolError(f"Expected text, got {type(value).__name__}.")
    if len(value) > MAX_SHOWN_CHARS:
        raise ToolError(
            f"A value is {len(value)} characters long; the limit is {MAX_SHOWN_CHARS} "
            "so it can be shown in full for confirmation. Shorten it and retry."
        )
    out: list[str] = []
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif unicodedata.category(ch) in _HIDDEN_CATEGORIES:
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= _BMP_MAX else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def describe_request(summary: str, values: Iterable[tuple[str, str | list[str] | None]]) -> str:
    """Consent text: the summary, then one line per value that will be sent.

    None, empty strings and empty lists are omitted, matching the client,
    which leaves them out of the request body.
    """
    lines = [summary]
    for label, value in values:
        if not value:
            continue
        rendered = ", ".join(shown(v) for v in value) if isinstance(value, list) else shown(value)
        lines.append(f"- {label}: {rendered}")
    return "\n".join(lines)


def _is_modern_protocol(ctx: Any) -> bool:
    rc = getattr(ctx, "request_context", None)
    version = getattr(rc, "protocol_version", None)
    return isinstance(version, str) and version in MODERN_PROTOCOL_VERSIONS


def _digest(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8", "surrogatepass")).hexdigest()


def _issue_nonce(message: str) -> str:
    now = time.monotonic()
    for stale in [n for n, (exp, _) in _PENDING.items() if exp <= now]:
        del _PENDING[stale]
    while len(_PENDING) >= _PENDING_MAX:
        del _PENDING[next(iter(_PENDING))]
    nonce = secrets.token_urlsafe(16)
    _PENDING[nonce] = (now + _PENDING_TTL_SECONDS, _digest(message))
    return nonce


def _consume_nonce(state: str | None, message: str) -> bool:
    if state is None or not state.startswith(_STATE_PREFIX):
        return False
    entry = _PENDING.pop(state.removeprefix(_STATE_PREFIX), None)
    if entry is None:
        return False
    expiry, digest = entry
    return expiry > time.monotonic() and secrets.compare_digest(digest, _digest(message))


def _consent_request(message: str) -> InputRequiredResult:
    params = ElicitRequestFormParams(
        message=message,
        requested_schema=get_elicitation_schema(_Confirmation),
    )
    return InputRequiredResult(
        input_requests={_CONSENT_KEY: ElicitRequest(params=params)},
        request_state=_STATE_PREFIX + _issue_nonce(message),
    )


def _check_consent_response(ctx: Any, action_description: str) -> None:
    responses = ctx.input_responses or {}
    response = responses.get(_CONSENT_KEY)
    if isinstance(response, ElicitResult) and response.action == "accept":
        return
    if isinstance(response, ElicitResult) and response.action == "decline":
        raise ElicitationDeclinedError(f"User declined: {action_description}")
    raise ElicitationCancelledError(f"User cancelled: {action_description}")


async def confirm_write(ctx: Any, action_description: str) -> InputRequiredResult | None:
    """Ask the user to confirm a write. Raise on decline/cancel.

    Returns an InputRequiredResult the tool must return as-is when the client
    still has to be asked (2026-07-28 connections); None once confirmed.
    """
    message = f"Confirm: {action_description}"
    if _is_modern_protocol(ctx):
        if not _consume_nonce(ctx.request_state, message):
            return _consent_request(message)
        _check_consent_response(ctx, action_description)
        return None
    result = await ctx.elicit(message, response_type=_Confirmation)
    match result:
        case AcceptedElicitation():
            return None
        case DeclinedElicitation():
            raise ElicitationDeclinedError(f"User declined: {action_description}")
        case CancelledElicitation():
            raise ElicitationCancelledError(f"User cancelled: {action_description}")
        case _:  # pragma: no cover  # why: ctx.elicit return type is exhausted above
            raise AssertionError(f"Unexpected elicitation result: {type(result).__name__}")


async def elicit_value(ctx: Any, prompt: str, response_type: Any) -> Any:
    """Ask the user to supply a typed value mid-call. Raise on decline/cancel.

    Wraps FastMCP 3.3's typed elicitation: `response_type` is forwarded to the
    client and serialised into JSON Schema, so primitives (str, int), `list[T]`,
    and Pydantic models all render as appropriate UI in the client.

    2026-07-28 connections cannot be asked mid-call, so the call fails before
    any request is sent and the caller can retry with the value as an argument.
    """
    if _is_modern_protocol(ctx):
        raise ToolError(f"Missing value; pass it as a tool argument and retry. {prompt}")
    result = await ctx.elicit(prompt, response_type=response_type)
    match result:
        case AcceptedElicitation():
            return result.data
        case DeclinedElicitation():
            raise ElicitationDeclinedError(f"User declined providing: {prompt}")
        case CancelledElicitation():
            raise ElicitationCancelledError(f"User cancelled providing: {prompt}")
        case _:  # pragma: no cover  # why: ctx.elicit return type is exhausted above
            raise AssertionError(f"Unexpected elicitation result: {type(result).__name__}")


def require_write_consent(
    describe: Describe,
    *,
    namespace: str,
    automatable: bool = False,
    prepare: Prepare | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator gating a write tool with the three safety layers.

    describe is the consent text, or a function building it from the tool's
    keyword arguments (use describe_request so every sent value is shown).

    namespace is the one the tool's sub-server is mounted under, so the
    bypass registry and log use the name hosts call (`<namespace>_<function>`).

    prepare(ctx, kwargs), if given, runs after the read-only check and before
    the consent prompt. It validates arguments and fills in missing values in
    `kwargs`, so one confirmation covers the final request.

    automatable=True marks the tool as bypass-eligible: when
    AKAHU_AUTOMATION_BYPASS=true, the elicit() prompt is skipped for these
    tools only.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        tool_name = f"{namespace}_{fn.__name__}"
        if automatable:
            _BYPASS_REGISTRY.add(tool_name)

        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            cfg = get_config()
            if cfg.read_only:
                raise ReadOnlyError(
                    "Write operations are disabled. To enable: set "
                    "AKAHU_READ_ONLY=false in the server's environment and restart "
                    "the MCP server. Each write will require your explicit confirmation "
                    "in your MCP client (or set AKAHU_AUTOMATION_BYPASS=true for "
                    "the automatable subset only)."
                )

            ctx = kwargs.get("ctx")
            call_kwargs = cast(dict[str, Any], kwargs)
            if prepare is not None:
                await prepare(ctx, call_kwargs)
            rendered = describe if isinstance(describe, str) else describe(call_kwargs)

            if automatable and cfg.automation_bypass:
                logger.info("[BYPASS] %s: %s", tool_name, rendered)
            else:
                if ctx is None:  # pragma: no cover
                    raise ToolError("Internal error: write tool missing ctx parameter.")
                ask = await confirm_write(ctx, rendered)
                if ask is not None:
                    return cast(R, ask)

            return await fn(*args, **call_kwargs)

        return wrapper

    return decorator


def bypass_eligible_tools() -> list[str]:
    """Exposed names of tools whose decorator declared automatable=True."""
    return sorted(_BYPASS_REGISTRY)
