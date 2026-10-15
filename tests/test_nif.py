"""Spanish NIF / NIE / CIF checksum tests.

The JSON fixture is shared with the WooCommerce plugin so both implementations agree.
python-stdnum (a dev-only dependency) is used as an independent oracle.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from stdnum.es import nif as stdnum_nif

from huella.nif import (
    cif_check_characters,
    dni_letter,
    is_valid_nif,
    normalize_nif,
    validate_nif,
)

CASES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "nif_cases.json").read_text(encoding="utf-8")
)
ALPHANUMERIC = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.mark.parametrize("case", CASES["valid"], ids=lambda c: c["nif"])
def test_valid_fixture(case: dict[str, str]) -> None:
    assert is_valid_nif(case["nif"])
    assert validate_nif(case["nif"]) == case["nif"]


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda c: c["why"])
def test_invalid_fixture(case: dict[str, str]) -> None:
    assert not is_valid_nif(case["nif"])
    with pytest.raises(ValueError, match="NIF"):
        validate_nif(case["nif"])


@pytest.mark.parametrize("case", CASES["normalised"], ids=lambda c: c["input"])
def test_normalisation(case: dict[str, str]) -> None:
    assert normalize_nif(case["input"]) == case["nif"]
    assert validate_nif(case["input"]) == case["nif"]


@given(st.integers(min_value=0, max_value=99_999_999))
def test_every_dni_with_its_letter_is_valid_and_any_other_letter_is_not(number: int) -> None:
    letter = dni_letter(number)
    assert is_valid_nif(f"{number:08d}{letter}")
    wrong = "TRWAGMYFPDXBNJZSQVHLCKE".replace(letter, "")[number % 22]
    assert not is_valid_nif(f"{number:08d}{wrong}")


@given(st.text(alphabet="0123456789", min_size=7, max_size=7))
def test_cif_accepts_exactly_its_digit_and_letter_controls(digits: str) -> None:
    controls = cif_check_characters(digits)
    for control in ALPHANUMERIC:
        assert is_valid_nif(f"B{digits}{control}") == (control in controls)


@given(
    st.tuples(
        st.sampled_from(ALPHANUMERIC),
        st.text(alphabet="0123456789", min_size=7, max_size=7),
        st.sampled_from(ALPHANUMERIC),
    ).map("".join)
)
def test_agrees_with_python_stdnum(candidate: str) -> None:
    assert is_valid_nif(candidate) == stdnum_nif.is_valid(candidate)


@pytest.mark.parametrize("number", [-1, 100_000_000])
def test_dni_letter_rejects_out_of_range(number: int) -> None:
    with pytest.raises(ValueError, match="8 digits"):
        dni_letter(number)


@pytest.mark.parametrize("digits", ["123456", "12345678", "123456A"])
def test_cif_check_characters_needs_seven_digits(digits: str) -> None:
    with pytest.raises(ValueError, match="7 digits"):
        cif_check_characters(digits)
