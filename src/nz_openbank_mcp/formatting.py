"""Small display helpers: currency, account masking, NZ dates, ISO parsing."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

# NZ bank-account format: BB-bbbb-AAAAAAA-SS
# (bank code - branch - account number - suffix)
_NZ_ACCOUNT_RE = re.compile(r"^(\d{2})-(\d{4})-(\d{7})-(\d{2,3})$")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

NZ_TZ = ZoneInfo("Pacific/Auckland")


CENT = Decimal("0.01")
MONEY_ROUNDING = ROUND_HALF_EVEN


def to_decimal(amount: float | int | Decimal) -> Decimal:
    """`amount` as a Decimal; floats go through their shortest repr.

    So 2.675 becomes the 2.675 a person typed, not the binary value just
    below it.
    """
    return Decimal(repr(amount)) if isinstance(amount, float) else Decimal(amount)


def to_cents(amount: float | int | Decimal) -> Decimal:
    """`amount` rounded to cents with banker's rounding (half to even)."""
    return to_decimal(amount).quantize(CENT, rounding=MONEY_ROUNDING)


def money_number(amount: Decimal) -> float:
    """`amount` rounded to cents, as a JSON number."""
    return float(to_cents(amount))


def format_money(amount: float | int | Decimal, currency: str | None = "NZD") -> str:
    """Format a numeric amount as a currency string.

    NZD uses the dollar sign; any other ISO 4217 code is used as a verbatim
    prefix. An empty code falls back to NZD; None (currency unknown) gives a
    bare number.

    >>> format_money(1234.56)
    '$1,234.56'
    >>> format_money(-89.99)
    '-$89.99'
    >>> format_money(1234.56, "USD")
    'USD 1,234.56'
    >>> format_money(-89.99, "EUR")
    '-EUR 89.99'
    """
    quantised = to_cents(amount)
    sign = "-" if quantised < 0 else ""
    absolute = abs(quantised)
    integer_part, _, fractional = format(absolute, "f").partition(".")
    with_commas = f"{int(integer_part):,}"
    if currency is None:
        return f"{sign}{with_commas}.{fractional}"
    if currency == "NZD" or not currency:
        return f"{sign}${with_commas}.{fractional}"
    return f"{sign}{currency} {with_commas}.{fractional}"


def mask_account(formatted: str | None) -> str:
    """Mask an account identifier, keeping only what identifies it to its owner.

    NZ format '<bank>-<branch>-<account>-<suffix>' becomes
    '<bank>-****-***<last4>-<suffix>'. Any other format has every digit except
    the last four replaced with '*', separators kept. None becomes ''.
    """
    if not formatted:
        return ""
    match = _NZ_ACCOUNT_RE.match(formatted)
    if match:
        bank, _branch, account, suffix = match.groups()
        return f"{bank}-****-***{account[-4:]}-{suffix}"
    to_mask = sum(ch.isdigit() for ch in formatted) - 4
    masked: list[str] = []
    for ch in formatted:
        if ch.isdigit() and to_mask > 0:
            masked.append("*")
            to_mask -= 1
        else:
            masked.append(ch)
    return "".join(masked)


def local_date(value: datetime) -> str:
    """NZ calendar date (YYYY-MM-DD) of an Akahu timestamp; naive means UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(NZ_TZ).date().isoformat()


def nz_today() -> date:
    return datetime.now(NZ_TZ).date()


def nz_day(value: str) -> date:
    """NZ calendar day named by a YYYY-MM-DD string or an ISO 8601 timestamp."""
    text = value.strip()
    if _DATE_ONLY_RE.match(text):
        return date.fromisoformat(text)
    return date.fromisoformat(local_date(parse_iso_date(text)))


def akahu_bound(value: str | None, *, end: bool) -> str | None:
    """Translate a date filter into an Akahu `start`/`end` query value.

    A bare YYYY-MM-DD is an NZ calendar day, inclusive at both ends. Akahu's
    `start` is exclusive and `end` inclusive, so both become the instant just
    before the relevant NZ midnight, in UTC. Blank means no bound. An ISO 8601
    timestamp passes through; Akahu reads one without an offset as UTC.
    Anything else raises ValueError before a request is made.
    """
    text = (value or "").strip()
    if not text:
        return None
    if not _DATE_ONLY_RE.match(text):
        try:
            parse_iso_date(text)
        except ValueError:
            raise ValueError(
                f"date filter {text!r} must be YYYY-MM-DD or an ISO 8601 timestamp"
            ) from None
        return text
    day = date.fromisoformat(text)
    if end:
        day += timedelta(days=1)
    instant = datetime.combine(day, time(), NZ_TZ) - timedelta(milliseconds=1)
    return instant.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso_date(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, accepting trailing 'Z' (UTC).

    Akahu returns timestamps like '2026-05-20T00:00:00.000Z'.
    """
    normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
    return datetime.fromisoformat(normalised)
