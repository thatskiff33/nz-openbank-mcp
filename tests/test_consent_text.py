"""Consent prompt text for every write tool: every sent value shown, no None."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation

from nz_openbank_mcp.models import RefreshResult, SupportRequest, VerifyNameResult


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    from nz_openbank_mcp import deps

    fake = MagicMock()
    fake.refresh_all = AsyncMock(return_value=RefreshResult(success=True))
    fake.refresh_one = AsyncMock(return_value=RefreshResult(success=True))
    fake.verify_name = AsyncMock(return_value=VerifyNameResult(success=True))
    fake.report_transaction_issue = AsyncMock(return_value=SupportRequest(success=True))
    monkeypatch.setattr(deps, "get_client", lambda: fake)
    return fake


def _prompt(ctx: MagicMock) -> str:
    message: str = ctx.elicit.await_args_list[-1][0][0]
    return message


async def test_refresh_all_prompt(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.accounts import refresh_all_accounts

    ctx = ctx_factory()
    await refresh_all_accounts(ctx=ctx)
    assert _prompt(ctx) == (
        "Confirm: Refresh data for all your connected accounts. This is rate-limited by your bank."
    )


async def test_verify_name_prompt_with_only_a_family_name(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.identity import verify_name

    ctx = ctx_factory()
    await verify_name(ctx=ctx, family_name="Smith")
    assert _prompt(ctx) == (
        "Confirm: Send this name to Akahu to check against the holder of every connected "
        "source. This sends an identity check to your bank and may incur a per-call charge.\n"
        '- family name: "Smith"'
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"family_name": "  "}, "family_name must not be blank"),
        ({"family_name": "Smith", "account_id": " "}, "account_id must not be blank"),
    ],
)
async def test_verify_name_blank_values_fail_before_consent(
    writable_env: None,
    ctx_factory: Callable[..., MagicMock],
    client: MagicMock,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    from nz_openbank_mcp.tools.identity import verify_name

    ctx = ctx_factory()
    with pytest.raises(ToolError, match=message):
        await verify_name(ctx=ctx, **kwargs)
    ctx.elicit.assert_not_awaited()
    client.verify_name.assert_not_awaited()


async def test_support_ticket_prompt_shows_every_sent_value(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    await report_transaction_issue(
        ctx=ctx,
        transaction_id="txn_1",
        issue_type="DUPLICATE",
        other_transaction_id="txn_2",
        fields=["merchant"],
        comment="Charged twice",
    )
    assert _prompt(ctx) == (
        "Confirm: Send this support ticket to a person at Akahu:\n"
        '- transaction: "txn_1"\n'
        '- type: "DUPLICATE"\n'
        '- duplicate of: "txn_2"\n'
        '- fields: "merchant"\n'
        '- comment: "Charged twice"'
    )
    client.report_transaction_issue.assert_awaited_once_with(
        "txn_1",
        issue_type="DUPLICATE",
        fields=["merchant"],
        comment="Charged twice",
        other_transaction_id="txn_2",
    )


async def test_elicited_fields_appear_in_the_single_consent_prompt(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [
        AcceptedElicitation(data=["category"]),
        AcceptedElicitation(data={}),
    ]
    await report_transaction_issue(
        ctx=ctx, transaction_id="txn_1", issue_type="ENRICHMENT_SUGGESTION"
    )
    assert ctx.elicit.await_count == 2
    assert _prompt(ctx).endswith('- type: "ENRICHMENT_SUGGESTION"\n- fields: "category"')


@pytest.mark.parametrize("answer", ["", "   ", None])
async def test_blank_elicited_duplicate_id_is_a_decline(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock, answer: Any
) -> None:
    from nz_openbank_mcp.safety import ElicitationDeclinedError
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    ctx.elicit.side_effect = [AcceptedElicitation(data=answer)]
    with pytest.raises(ElicitationDeclinedError, match="no transaction id"):
        await report_transaction_issue(ctx=ctx, transaction_id="txn_1", issue_type="DUPLICATE")
    assert ctx.elicit.await_count == 1
    client.report_transaction_issue.assert_not_awaited()


async def test_blank_transaction_id_fails_before_any_prompt(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    ctx = ctx_factory()
    with pytest.raises(ToolError, match="transaction_id must not be blank"):
        await report_transaction_issue(
            ctx=ctx, transaction_id=" ", issue_type="DUPLICATE", other_transaction_id="txn_2"
        )
    ctx.elicit.assert_not_awaited()


async def test_value_too_long_to_show_fails_before_consent(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.identity import verify_name

    ctx = ctx_factory()
    with pytest.raises(ToolError, match="shown in full"):
        await verify_name(ctx=ctx, family_name="x" * 1001)
    ctx.elicit.assert_not_awaited()
    client.verify_name.assert_not_awaited()


async def test_no_prompt_contains_a_none_literal(
    writable_env: None, ctx_factory: Callable[..., MagicMock], client: MagicMock
) -> None:
    from nz_openbank_mcp.tools.accounts import refresh_account, refresh_all_accounts
    from nz_openbank_mcp.tools.identity import verify_name
    from nz_openbank_mcp.tools.transactions import report_transaction_issue

    calls: list[Callable[[Any], Any]] = [
        lambda ctx: refresh_all_accounts(ctx=ctx),
        lambda ctx: refresh_account(ctx=ctx, account_id="acc_1"),
        lambda ctx: verify_name(ctx=ctx, family_name="Smith"),
        lambda ctx: verify_name(ctx=ctx, family_name="Smith", account_id="acc_1"),
        lambda ctx: report_transaction_issue(
            ctx=ctx, transaction_id="txn_1", issue_type="DUPLICATE", other_transaction_id="t2"
        ),
        lambda ctx: report_transaction_issue(
            ctx=ctx, transaction_id="txn_1", issue_type="ENRICHMENT_ERROR", fields=["merchant"]
        ),
    ]
    for call in calls:
        ctx = ctx_factory()
        await call(ctx)
        assert "None" not in _prompt(ctx)
