"""Spanish tax ID checksums: NIF of individuals (DNI, K/L/M), NIE and CIF of organisations.

All three are 9 characters. The last one is a control character computed from the others:

- DNI ``12345678Z``: 8 digits, letter = ``TRWAGMYFPDXBNJZSQVHLCKE[number % 23]``.
- NIE ``X1234567L``: X/Y/Z stand for 0/1/2, then the DNI rule on the 8 digits.
- K/L/M ``M1234567L``: individuals without DNI/NIE; the DNI rule on the 7 digits.
- CIF ``B12345674``: organisation letter, 7 digits, then a Luhn-style digit or its letter
  (``JABCDEFGHI``). Both forms are accepted for every organisation letter, as python-stdnum does:
  rejecting a real customer's CIF would block their invoices.
"""

import re

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_CIF_ORGANISATION_LETTERS = "ABCDEFGHJNPQRSUVW"
_CIF_CONTROL_LETTERS = "JABCDEFGHI"
_NIF_SHAPE = re.compile(r"[0-9A-Z]\d{7}[0-9A-Z]")
_SEPARATORS = str.maketrans("", "", " -.")


def normalize_nif(value: str) -> str:
    """Uppercase and drop spaces, hyphens and dots: ``" b-1234567.4"`` → ``"B12345674"``."""
    return value.translate(_SEPARATORS).upper()


def dni_letter(number: int) -> str:
    """Control letter of a DNI number (also used for NIE and K/L/M).

    >>> dni_letter(12345678)
    'Z'
    """
    if not 0 <= number <= 99_999_999:
        raise ValueError(f"a DNI number has at most 8 digits, got {number}")
    return _DNI_LETTERS[number % 23]


def cif_check_characters(digits: str) -> str:
    """The two accepted CIF controls for 7 digits: the digit and its letter.

    >>> cif_check_characters("1234567")
    '4D'
    """
    if not re.fullmatch(r"\d{7}", digits):
        raise ValueError(f"a CIF body has exactly 7 digits, got {digits!r}")
    total = 0
    for position, char in enumerate(digits):
        value = int(char)
        if position % 2 == 0:  # 1st, 3rd, 5th and 7th digits are doubled, then digit-summed
            value = sum(divmod(value * 2, 10))
        total += value
    check = (10 - total % 10) % 10
    return f"{check}{_CIF_CONTROL_LETTERS[check]}"


def is_valid_nif(value: str) -> bool:
    """True if ``value`` (after :func:`normalize_nif`) is a checksum-valid NIF, NIE or CIF.

    >>> is_valid_nif("89890001K"), is_valid_nif("B12345678")
    (True, False)
    """
    nif = normalize_nif(value)
    if not nif.isascii() or not _NIF_SHAPE.fullmatch(nif):
        return False
    first, digits, control = nif[0], nif[1:8], nif[8]
    if first.isdigit():
        return control == dni_letter(int(nif[:8]))
    if first in _NIE_PREFIX:
        return control == dni_letter(int(_NIE_PREFIX[first] + digits))
    if first in "KLM":
        return control == dni_letter(int(digits))
    if first in _CIF_ORGANISATION_LETTERS:
        return control in cif_check_characters(digits)
    return False


def validate_nif(value: str) -> str:
    """Return the normalised NIF, or raise ``ValueError`` if it is not checksum-valid."""
    nif = normalize_nif(value)
    if not is_valid_nif(nif):
        raise ValueError(f"invalid Spanish NIF: {value!r}")
    return nif
