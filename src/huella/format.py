"""Exact text forms of amounts, dates and timestamps (SPEC 3.3, 3.6).

Every value that is hashed is written to the XML as the *same* string, so these functions are
the single place where a value becomes text. Rounding is a separate, explicit step:
``format_amount(round_amount(x))``. ``format_amount`` itself never rounds; a value with more than
two decimals reaching it is a bug upstream and raises ``ValueError``.
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

_CENT = Decimal("0.01")
_AMOUNT_LIMIT = Decimal("1E12")  # XSD ImporteSgn12.2Type allows 12 integer digits
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")


def _to_decimal(value: Decimal | int) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError(f"amount must be Decimal or int, not {type(value).__name__}")
    amount = Decimal(value)
    if not amount.is_finite():
        raise ValueError(f"amount must be finite, got {amount}")
    return amount


def round_amount(value: Decimal | int) -> Decimal:
    """Round to cents, half away from zero (the same rule as PHP ``round()``).

    >>> round_amount(Decimal("17.3544")), round_amount(Decimal("1.005"))
    (Decimal('17.35'), Decimal('1.01'))
    """
    return _to_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def format_amount(value: Decimal | int) -> str:
    """Amount as text: always 2 decimals, dot separator, no thousands separator.

    >>> format_amount(Decimal("123.4"))
    '123.40'
    """
    amount = _to_decimal(value)
    if abs(amount) >= _AMOUNT_LIMIT:
        raise ValueError(f"amount {amount} has more than 12 integer digits")
    cents = amount.quantize(_CENT)
    if cents != amount:
        raise ValueError(f"amount {amount} has more than 2 decimal places; round it first")
    if cents.is_zero():
        cents = abs(cents)  # never write "-0.00"
    return f"{cents:f}"


def format_date(value: date) -> str:
    """Date as ``DD-MM-YYYY``.

    >>> format_date(date(2026, 11, 20))
    '20-11-2026'
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"expected a date, not {type(value).__name__}")
    return f"{value.day:02d}-{value.month:02d}-{value.year:04d}"


def timestamp_madrid(instant: datetime) -> str:
    """Instant as Madrid local time with explicit offset, truncated to whole seconds.

    >>> from datetime import UTC
    >>> timestamp_madrid(datetime(2024, 1, 1, 18, 20, 30, tzinfo=UTC))
    '2024-01-01T19:20:30+01:00'
    """
    if instant.utcoffset() is None:
        raise ValueError("timestamp needs a time-zone-aware datetime")
    text = instant.astimezone(MADRID).isoformat(timespec="seconds")
    if not TIMESTAMP_PATTERN.fullmatch(text):
        raise ValueError(f"Madrid offset cannot be written as +HH:MM for this instant: {text}")
    return text
