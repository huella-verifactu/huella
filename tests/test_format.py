"""Formatting tests: the exact strings that go into both the hash and the XML (SPEC 3.3, 3.6)."""

import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huella.format import format_amount, format_date, round_amount, timestamp_madrid

AMOUNT_RE = re.compile(r"-?\d{1,12}\.\d{2}")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
MAX_AMOUNT = Decimal("999999999999.99")

cents = st.decimals(min_value=-MAX_AMOUNT, max_value=MAX_AMOUNT, places=2)

# --- format_amount -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("123.45"), "123.45"),
        (Decimal("123.4"), "123.40"),
        (Decimal("123.450"), "123.45"),
        (Decimal("0"), "0.00"),
        (Decimal("-0.00"), "0.00"),
        (Decimal("-12.5"), "-12.50"),
        (Decimal("1E+2"), "100.00"),
        (Decimal("1234567.89"), "1234567.89"),
        (MAX_AMOUNT, "999999999999.99"),
        (-MAX_AMOUNT, "-999999999999.99"),
        (100, "100.00"),
    ],
)
def test_format_amount(value: Decimal | int, expected: str) -> None:
    assert format_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        Decimal("1.005"),
        Decimal("0.001"),
        Decimal("1000000000000.00"),
        Decimal("-1000000000000"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_format_amount_rejects_values_that_cannot_be_written_exactly(value: Decimal) -> None:
    with pytest.raises(ValueError, match="amount"):
        format_amount(value)


@pytest.mark.parametrize("value", [123.45, "123.45", True, None])
def test_format_amount_rejects_non_decimal_types(value: object) -> None:
    with pytest.raises(TypeError):
        format_amount(value)  # type: ignore[arg-type]


@given(cents)
def test_format_amount_is_exact_and_matches_the_xsd_shape(value: Decimal) -> None:
    text = format_amount(value)
    assert AMOUNT_RE.fullmatch(text)
    assert Decimal(text) == value


# --- round_amount ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.005"), Decimal("1.01")),
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("2.675"), Decimal("2.68")),  # a float would give 2.67
        (Decimal("-1.005"), Decimal("-1.01")),  # half away from zero, like PHP round()
        (Decimal("17.3544"), Decimal("17.35")),
        (Decimal("123.4"), Decimal("123.40")),
        (100, Decimal("100.00")),
    ],
)
def test_round_amount_rounds_half_up_to_cents(value: Decimal | int, expected: Decimal) -> None:
    result = round_amount(value)
    assert result == expected
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize("value", [1.005, "1.005", False, None])
def test_round_amount_rejects_non_decimal_types(value: object) -> None:
    with pytest.raises(TypeError):
        round_amount(value)  # type: ignore[arg-type]


def test_round_amount_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="amount"):
        round_amount(Decimal("NaN"))


@given(st.decimals(min_value=-MAX_AMOUNT, max_value=MAX_AMOUNT, places=6))
def test_round_then_format_never_fails_and_moves_less_than_half_a_cent(value: Decimal) -> None:
    rounded = round_amount(value)
    assert abs(rounded - value) <= Decimal("0.005")
    assert Decimal(format_amount(rounded)) == rounded


# --- format_date -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2024, 1, 1), "01-01-2024"),
        (date(2026, 11, 20), "20-11-2026"),
        (date(2026, 12, 31), "31-12-2026"),
        (date(999, 3, 4), "04-03-0999"),
    ],
)
def test_format_date(value: date, expected: str) -> None:
    assert format_date(value) == expected


def test_format_date_rejects_datetime() -> None:
    # A datetime would silently drop its time zone; the caller must pick the local date.
    with pytest.raises(TypeError):
        format_date(datetime(2026, 11, 20, tzinfo=UTC))


@given(st.dates())
def test_format_date_round_trips(value: date) -> None:
    assert datetime.strptime(format_date(value), "%d-%m-%Y").date() == value  # noqa: DTZ007


# --- timestamp_madrid --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        pytest.param(
            datetime(2024, 1, 1, 18, 20, 30, tzinfo=UTC),
            "2024-01-01T19:20:30+01:00",
            id="winter-official-vector",
        ),
        pytest.param(
            datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC), "2026-07-01T12:00:00+02:00", id="summer"
        ),
        pytest.param(
            datetime(2026, 11, 20, 10, 15, 3, 999_999, tzinfo=UTC),
            "2026-11-20T11:15:03+01:00",
            id="microseconds-truncated",
        ),
        pytest.param(
            datetime(2026, 11, 20, 23, 30, 0, tzinfo=UTC),
            "2026-11-21T00:30:00+01:00",
            id="madrid-date-differs-from-utc",
        ),
        pytest.param(
            datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone(timedelta(hours=-5))),
            "2026-11-20T18:00:00+01:00",
            id="non-utc-input",
        ),
        pytest.param(
            datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC),
            "2026-03-29T01:59:59+01:00",
            id="last-second-before-spring-forward",
        ),
        pytest.param(
            datetime(2026, 3, 29, 1, 0, 0, tzinfo=UTC),
            "2026-03-29T03:00:00+02:00",
            id="spring-forward",
        ),
        pytest.param(
            datetime(2026, 10, 25, 0, 30, 0, tzinfo=UTC),
            "2026-10-25T02:30:00+02:00",
            id="fall-back-first-0230",
        ),
        pytest.param(
            datetime(2026, 10, 25, 1, 30, 0, tzinfo=UTC),
            "2026-10-25T02:30:00+01:00",
            id="fall-back-second-0230",
        ),
    ],
)
def test_timestamp_madrid(instant: datetime, expected: str) -> None:
    assert timestamp_madrid(instant) == expected


def test_timestamp_madrid_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        timestamp_madrid(datetime(2026, 11, 20, 10, 15, 3))  # noqa: DTZ001


def test_timestamp_madrid_rejects_offsets_with_seconds() -> None:
    # Before 1901 Madrid used local mean time (-00:14:44), which no XSD timestamp can carry.
    with pytest.raises(ValueError, match="offset"):
        timestamp_madrid(datetime(1890, 1, 1, tzinfo=UTC))


@given(
    st.datetimes(
        min_value=datetime(1970, 1, 1),  # noqa: DTZ001
        max_value=datetime(2100, 1, 1),  # noqa: DTZ001
        timezones=st.just(UTC),
    )
)
def test_timestamp_madrid_is_the_same_instant_to_the_second(instant: datetime) -> None:
    text = timestamp_madrid(instant)
    assert TIMESTAMP_RE.fullmatch(text)
    assert datetime.fromisoformat(text) == instant.replace(microsecond=0)
