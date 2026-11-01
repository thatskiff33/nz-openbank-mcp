"""Tests for formatting helpers: money formatting, account masking, ISO dates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def test_format_money_nzd_uses_dollar_symbol() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1234.56) == "$1,234.56"
    assert format_money(1234.56, "NZD") == "$1,234.56"


def test_format_money_nzd_negative() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(-89.99) == "-$89.99"


def test_format_money_zero() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(0) == "$0.00"
    assert format_money(0, "USD") == "USD 0.00"


def test_format_money_usd_uses_iso_prefix() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1234.56, "USD") == "USD 1,234.56"
    assert format_money(-89.99, "USD") == "-USD 89.99"


def test_format_money_eur_uses_iso_prefix() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1234.56, "EUR") == "EUR 1,234.56"


def test_format_money_php_uses_iso_prefix() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1234.56, "PHP") == "PHP 1,234.56"


def test_format_money_unknown_iso_code_passes_through() -> None:
    """Any non-NZD currency string is prefixed verbatim."""
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1000, "XOF") == "XOF 1,000.00"


def test_format_money_empty_currency_falls_back_to_nzd() -> None:
    """Empty currency defaults to NZD formatting."""
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1234.56, "") == "$1,234.56"


def test_format_money_large_number_thousands_separator() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(1_234_567.89) == "$1,234,567.89"
    assert format_money(1_234_567.89, "USD") == "USD 1,234,567.89"


def test_format_money_rounds_half_to_even() -> None:
    """Banker's rounding (ROUND_HALF_EVEN) applies to all currencies."""
    from nz_openbank_mcp.formatting import format_money

    assert format_money(0.005) == "$0.00"
    assert format_money(0.015) == "$0.02"
    assert format_money(0.005, "USD") == "USD 0.00"
    assert format_money(0.015, "USD") == "USD 0.02"


def test_mask_account_full_format() -> None:
    from nz_openbank_mcp.formatting import mask_account

    formatted = "-".join(["01", "1234", "1234567", "00"])
    assert mask_account(formatted) == "01-****-***4567-00"


def test_mask_account_without_masked_digits_is_unchanged() -> None:
    from nz_openbank_mcp.formatting import mask_account

    assert mask_account("****") == "****"
    assert mask_account("") == ""
    assert mask_account("SYNTHETIC-CHECKING-ACCOUNT") == "SYNTHETIC-CHECKING-ACCOUNT"
    assert mask_account("1234") == "1234"


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("4111 1111 1111 1234", "**** **** **** 1234"),  # card-style, spaced
        ("4111111111111234", "************1234"),
        ("12-3456-789012-001", "**-****-*****2-001"),  # NZ-like but wrong widths
        ("GB29NWBK60161331926819", "GB**NWBK**********6819"),  # unknown format
        ("12345", "*2345"),
    ],
)
def test_mask_account_fails_closed_on_other_formats(raw: str, masked: str) -> None:
    from nz_openbank_mcp.formatting import mask_account

    assert mask_account(raw) == masked


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        (datetime(2026, 10, 17, 11, 0, tzinfo=UTC), "2026-10-18"),
        (datetime(2026, 6, 17, 12, 0, tzinfo=UTC), "2026-06-18"),
        (datetime(2026, 6, 17, 11, 59), "2026-06-17"),  # naive is treated as UTC
    ],
)
def test_local_date_uses_nz_calendar(stamp: datetime, expected: str) -> None:
    from nz_openbank_mcp.formatting import local_date

    assert local_date(stamp) == expected


@pytest.mark.parametrize(
    ("value", "end", "expected"),
    [
        ("2026-10-18", False, "2026-10-17T10:59:59.999Z"),
        ("2026-10-18", True, "2026-10-18T10:59:59.999Z"),
        ("2026-06-18", False, "2026-06-17T11:59:59.999Z"),
        (" 2026-06-18 ", True, "2026-06-18T11:59:59.999Z"),
        ("2026-04-05", True, "2026-04-05T11:59:59.999Z"),  # day DST ends
        ("2026-05-01T00:00:00Z", False, "2026-05-01T00:00:00Z"),
        (None, True, None),
    ],
)
def test_akahu_bound(value: str | None, end: bool, expected: str | None) -> None:
    from nz_openbank_mcp.formatting import akahu_bound

    assert akahu_bound(value, end=end) == expected


def test_akahu_bound_rejects_impossible_date() -> None:
    from nz_openbank_mcp.formatting import akahu_bound

    with pytest.raises(ValueError, match="day"):
        akahu_bound("2026-02-30", end=False)


def test_nz_today_is_a_date() -> None:
    from datetime import date

    from nz_openbank_mcp.formatting import nz_today

    assert isinstance(nz_today(), date)


def test_mask_account_none_returns_empty() -> None:
    from nz_openbank_mcp.formatting import mask_account

    assert mask_account(None) == ""


def test_parse_iso_date_with_z() -> None:
    from nz_openbank_mcp.formatting import parse_iso_date

    dt = parse_iso_date("2026-05-20T00:00:00.000Z")
    assert dt == datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC)


def test_parse_iso_date_with_offset() -> None:
    from nz_openbank_mcp.formatting import parse_iso_date

    dt = parse_iso_date("2026-05-20T12:00:00+12:00")
    assert dt.utcoffset() is not None


def test_parse_iso_date_invalid_raises() -> None:
    from nz_openbank_mcp.formatting import parse_iso_date

    with pytest.raises(ValueError):
        parse_iso_date("not a date")
