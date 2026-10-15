"""Huella (record hash) tests.

The three vectors come from the AEAT huella spec v0.1.2, section 6
(`src/huella/specs/v1_0/Veri-Factu_especificaciones_huella_hash_registros.pdf`).
The trap tests document inputs that look equivalent but produce a different hash.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import astuple, dataclass, replace

import pytest

from huella.hash import huella_alta, huella_anulacion

CASE_1 = "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60"
CASE_2 = "F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97"
CASE_3 = "177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68"

HEX64_UPPER = re.compile(r"[0-9A-F]{64}")


@dataclass(frozen=True)
class Alta:
    """Inputs of an alta hash; defaults are official case 1."""

    nif: str = "89890001K"
    num: str = "12345678/G33"
    fecha: str = "01-01-2024"
    tipo: str = "F1"
    cuota: str = "12.35"
    importe: str = "123.45"
    previa: str | None = None
    ts: str = "2024-01-01T19:20:30+01:00"

    def huella(self) -> str:
        return huella_alta(
            nif=self.nif,
            num=self.num,
            fecha=self.fecha,
            tipo=self.tipo,
            cuota=self.cuota,
            importe=self.importe,
            previa=self.previa,
            ts=self.ts,
        )


CASE_1_ALTA = Alta()
CASE_2_ALTA = replace(
    CASE_1_ALTA, num="12345679/G34", previa=CASE_1, ts="2024-01-01T19:20:35+01:00"
)


# --- Official AEAT vectors -------------------------------------------------------------


def test_case_1_first_alta_matches_official_vector() -> None:
    assert CASE_1_ALTA.huella() == CASE_1


def test_case_2_chained_alta_matches_official_vector() -> None:
    assert CASE_2_ALTA.huella() == CASE_2


def test_case_3_anulacion_of_case_2_matches_official_vector() -> None:
    result = huella_anulacion(
        nif="89890001K",
        num="12345679/G34",
        fecha="01-01-2024",
        previa=CASE_2,
        ts="2024-01-01T19:20:40+01:00",
    )
    assert result == CASE_3


# --- Output shape and equivalences the spec allows --------------------------------------


def test_output_is_64_uppercase_hex() -> None:
    assert HEX64_UPPER.fullmatch(CASE_1_ALTA.huella())


def test_empty_previous_huella_is_the_same_as_none() -> None:
    assert replace(CASE_1_ALTA, previa="").huella() == CASE_1


def test_values_are_trimmed_before_hashing() -> None:
    padded = Alta(
        nif=" 89890001K ",
        num="  12345678/G33",
        fecha="01-01-2024  ",
        tipo=" F1",
        cuota="12.35 ",
        importe="\t123.45\n",
        previa="  ",
        ts=" 2024-01-01T19:20:30+01:00 ",
    )
    assert padded.huella() == CASE_1


def test_anulacion_first_record_hashes_with_empty_previous() -> None:
    chain_input = (
        "IDEmisorFacturaAnulada=89890001K&NumSerieFacturaAnulada=12345679/G34"
        "&FechaExpedicionFacturaAnulada=01-01-2024&Huella="
        "&FechaHoraHusoGenRegistro=2024-01-01T19:20:40+01:00"
    )
    expected = hashlib.sha256(chain_input.encode()).hexdigest().upper()
    result = huella_anulacion(
        nif="89890001K",
        num="12345679/G34",
        fecha="01-01-2024",
        previa=None,
        ts="2024-01-01T19:20:40+01:00",
    )
    assert result == expected


def test_alta_arguments_are_keyword_only() -> None:
    # cuota and importe are both amount strings; a positional swap would hash silently.
    untyped: Callable[..., str] = huella_alta
    with pytest.raises(TypeError):
        untyped(*astuple(CASE_1_ALTA))


# --- Hash traps: each looks harmless and each changes the hash (SPEC section 3.4) ------


@pytest.mark.parametrize(
    "trap",
    [
        pytest.param(replace(CASE_1_ALTA, importe="123.4"), id="amount-one-decimal"),
        pytest.param(replace(CASE_1_ALTA, importe="123,45"), id="amount-comma-separator"),
        pytest.param(replace(CASE_1_ALTA, ts="2024-01-01T18:20:30+00:00"), id="timestamp-in-utc"),
        pytest.param(replace(CASE_1_ALTA, ts="2024-01-01T18:20:30Z"), id="timestamp-with-z"),
        pytest.param(replace(CASE_1_ALTA, num="12345678%2FG33"), id="number-url-encoded"),
        pytest.param(replace(CASE_1_ALTA, fecha="2024-01-01"), id="date-iso-format"),
    ],
)
def test_trap_changes_the_hash(trap: Alta) -> None:
    assert trap.huella() != CASE_1


def test_trap_lowercase_previous_huella_changes_the_hash() -> None:
    assert replace(CASE_2_ALTA, previa=CASE_1.lower()).huella() != CASE_2


def test_trap_omitting_the_empty_huella_field_changes_the_hash() -> None:
    without_huella = (
        "IDEmisorFactura=89890001K&NumSerieFactura=12345678/G33"
        "&FechaExpedicionFactura=01-01-2024&TipoFactura=F1&CuotaTotal=12.35"
        "&ImporteTotal=123.45&FechaHoraHusoGenRegistro=2024-01-01T19:20:30+01:00"
    )
    assert hashlib.sha256(without_huella.encode()).hexdigest().upper() != CASE_1
