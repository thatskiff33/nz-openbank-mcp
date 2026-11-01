"""Tests for formatting helpers: money formatting, account masking, ISO dates."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
        (datetime(2026, 6, 17, 12, 0), "2026-06-18"),  # naive is UTC, not NZ local
    ],
)
def test_local_date_uses_nz_calendar(
    stamp: datetime, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from nz_openbank_mcp.formatting import local_date

    # A machine clock east of UTC exposes any use of system local time.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        assert local_date(stamp) == expected
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize(
    ("value", "end", "expected"),
    [
        ("2026-10-18", False, "2026-10-17T10:59:59.999Z"),
        ("2026-10-18", True, "2026-10-18T10:59:59.999Z"),
        ("2026-06-18", False, "2026-06-17T11:59:59.999Z"),
        (" 2026-06-18 ", True, "2026-06-18T11:59:59.999Z"),
        ("2026-04-05", False, "2026-04-04T10:59:59.999Z"),  # day NZDT ends
        ("2026-04-05", True, "2026-04-05T11:59:59.999Z"),
        ("2026-09-27", False, "2026-09-26T11:59:59.999Z"),  # day NZDT starts
        ("2026-09-27", True, "2026-09-27T10:59:59.999Z"),
        ("", False, None),
        ("   ", True, None),
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


@pytest.mark.parametrize("bad", ["2026-5-1", "yesterday", "31/12/2025"])
def test_akahu_bound_rejects_other_formats(bad: str) -> None:
    from nz_openbank_mcp.formatting import akahu_bound

    with pytest.raises(ValueError, match="YYYY-MM-DD or an ISO 8601"):
        akahu_bound(bad, end=True)


def test_nz_today_uses_nz_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date, tzinfo

    from nz_openbank_mcp import formatting

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Frozen:
            instant = cls(2026, 10, 17, 11, 30, tzinfo=UTC)  # 12:30am NZDT on the 18th
            return instant.astimezone(tz)

    monkeypatch.setattr(formatting, "datetime", Frozen)
    assert formatting.nz_today() == date(2026, 10, 18)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-18", "2026-10-18"),
        (" 2026-10-18 ", "2026-10-18"),
        ("2026-10-17T11:00:00Z", "2026-10-18"),
        ("2026-10-18T08:00:00+13:00", "2026-10-18"),
    ],
)
def test_nz_day(value: str, expected: str) -> None:
    from nz_openbank_mcp.formatting import nz_day

    assert nz_day(value).isoformat() == expected


def test_format_money_unknown_currency_is_bare_number() -> None:
    from nz_openbank_mcp.formatting import format_money

    assert format_money(-1234.5, None) == "-1,234.50"


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

    with pytest.raises(ValueError, match="isoformat"):
        parse_iso_date("not a date")


# ---------- money rounding ----------

HALF_CENTS = [Decimal(n) / 1000 for n in range(-20_005, 20_006, 10)]


def test_sweep_covers_only_half_cent_boundaries() -> None:
    assert HALF_CENTS[0] == Decimal("-20.005")
    assert all(str(d).endswith("5") and d.as_tuple().exponent == -3 for d in HALF_CENTS)


@pytest.mark.parametrize("value", HALF_CENTS, ids=str)
def test_half_cent_rounds_to_the_even_cent(value: Decimal) -> None:
    from nz_openbank_mcp.formatting import to_cents

    cents = to_cents(value)
    assert abs(cents - value) == Decimal("0.005")
    assert int(cents * 100) % 2 == 0


def test_half_cent_from_float_matches_from_decimal() -> None:
    from nz_openbank_mcp.formatting import to_cents

    for value in HALF_CENTS:
        assert to_cents(float(value)) == to_cents(value), value


def test_known_float_traps_round_as_written() -> None:
    from nz_openbank_mcp.formatting import format_money, money_number, to_cents

    # 2.675 and 1.005 are stored just below the half in binary.
    assert to_cents(2.675) == Decimal("2.68")
    assert to_cents(1.005) == Decimal("1.00")
    assert to_cents(1.015) == Decimal("1.02")
    assert format_money(2.675) == "$2.68"
    assert money_number(Decimal("-0.125")) == -0.12
    assert money_number(Decimal("12.345")) == 12.34


def test_money_number_agrees_with_display() -> None:
    from nz_openbank_mcp.formatting import format_money, money_number

    for value in HALF_CENTS:
        shown = format_money(value, None).replace(",", "")
        assert money_number(value) == float(shown), value


def test_to_decimal_is_exact() -> None:
    from nz_openbank_mcp.formatting import to_decimal

    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(-82.45) == Decimal("-82.45")
    assert to_decimal(5) == Decimal(5)
    assert to_decimal(Decimal("1.005")) == Decimal("1.005")


def test_models_parse_json_floats_exactly() -> None:
    from nz_openbank_mcp.models import Balance

    balance = Balance.model_validate({"current": 0.1, "available": 1.005, "limit": "7.10"})
    assert balance.current == Decimal("0.1")
    assert balance.available == Decimal("1.005")
    assert balance.limit == Decimal("7.10")
