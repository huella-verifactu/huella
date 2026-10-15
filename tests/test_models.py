"""Record models: every rule in SPEC 3.3 plus the AEAT business validations in v1 scope."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from huella.hash import hash_record, huella_alta, huella_anulacion
from huella.models import (
    ChainLink,
    Correction,
    InvoiceAlta,
    InvoiceAnulacion,
    Recipient,
    SistemaInformatico,
)

CASE_2 = "F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97"
CASE_3 = "177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68"


def f2(**overrides: Any) -> dict[str, Any]:
    """A valid simplified invoice as the API would receive it (amounts as strings)."""
    data: dict[str, Any] = {
        "issuer_nif": "B12345674",
        "issuer_name": "TIENDA EJEMPLO SL",
        "number": "2026-000123",
        "issue_date": "2026-01-20",
        "type": "F2",
        "description": "Venta online - pedido 1234",
        "tax_lines": [{"rate": "21.00", "base": "82.64", "tax": "17.36"}],
        "total": "100.00",
    }
    return data | overrides


def f1(**overrides: Any) -> dict[str, Any]:
    return f2(type="F1", recipient={"name": "ACME SL", "nif": "A1234567D"}) | overrides


def r1(**overrides: Any) -> dict[str, Any]:
    return (
        f1(
            type="R1",
            number="2026-R-0007",
            tax_lines=[{"rate": "21.00", "base": "-41.32", "tax": "-8.68"}],
            total="-50.00",
            rectifies=[{"number": "2026-000100", "issue_date": "2026-01-02"}],
        )
        | overrides
    )


def error_locations(exc: pytest.ExceptionInfo[ValidationError]) -> list[str]:
    return [".".join(str(part) for part in error["loc"]) for error in exc.value.errors()]


# --- Valid invoices --------------------------------------------------------------------------


def test_valid_simplified_invoice() -> None:
    alta = InvoiceAlta.model_validate(f2())
    assert alta.issue_date == date(2026, 1, 20)
    assert alta.tax_lines[0].tax == Decimal("17.36")
    assert alta.cuota_total == Decimal("17.36")
    assert alta.recipient is None
    assert alta.correction is Correction.NONE


def test_valid_full_invoice_with_spanish_recipient() -> None:
    alta = InvoiceAlta.model_validate(f1())
    assert alta.recipient is not None
    assert alta.recipient.nif == "A1234567D"


def test_valid_full_invoice_with_eu_recipient() -> None:
    eu = {"name": "ACME SAS", "country": "FR", "id_type": "02", "id": "FR12345678901"}
    alta = InvoiceAlta.model_validate(f1(recipient=eu))
    assert alta.recipient is not None
    assert alta.recipient.id == "FR12345678901"


def test_greek_vat_numbers_use_the_el_prefix() -> None:
    greek = {"name": "ACME AE", "country": "GR", "id_type": "02", "id": "EL123456789"}
    assert InvoiceAlta.model_validate(f1(recipient=greek)).recipient is not None


def test_valid_corrective_invoice_with_negative_amounts() -> None:
    alta = InvoiceAlta.model_validate(r1())
    assert alta.total == Decimal("-50.00")
    assert alta.rectifies[0].number == "2026-000100"


def test_valid_r5_without_recipient() -> None:
    data = r1(type="R5")
    del data["recipient"]
    assert InvoiceAlta.model_validate(data).type == "R5"


def test_several_rates_and_nif_normalisation() -> None:
    lines = [
        {"rate": "21", "base": "10.00", "tax": "2.10"},
        {"rate": "10.00", "base": "10.00", "tax": "1.00"},
        {"rate": "4", "base": "10.00", "tax": "0.40"},
    ]
    alta = InvoiceAlta.model_validate(f2(issuer_nif="b-1234567.4", tax_lines=lines, total="33.50"))
    assert alta.issuer_nif == "B12345674"
    assert alta.cuota_total == Decimal("3.50")


def test_rounding_tolerance_of_one_cent_per_line() -> None:
    line = {"rate": "21.00", "base": "0.05", "tax": "0.02"}  # exact 0.0105 -> 0.01, off by 0.01
    assert InvoiceAlta.model_validate(f2(tax_lines=[line], total="0.07"))


def test_free_order_is_allowed() -> None:
    line = {"rate": "21.00", "base": "0.00", "tax": "0.00"}
    assert InvoiceAlta.model_validate(f2(tax_lines=[line], total="0.00")).total == 0


def test_models_are_immutable() -> None:
    alta = InvoiceAlta.model_validate(f2())
    with pytest.raises(ValidationError):
        alta.total = Decimal("1.00")


# --- Invalid invoices: each must fail on the named field --------------------------------------


@pytest.mark.parametrize(
    ("data", "location"),
    [
        pytest.param(f2(issuer_nif="B12345678"), "issuer_nif", id="issuer-nif-checksum"),
        pytest.param(f2(issuer_name=""), "issuer_name", id="issuer-name-empty"),
        pytest.param(f2(issuer_name="X" * 121), "issuer_name", id="issuer-name-too-long"),
        pytest.param(f2(number=""), "number", id="number-empty"),
        pytest.param(f2(number="A" * 61), "number", id="number-too-long"),
        pytest.param(f2(number="2026=1"), "number", id="number-equals-sign"),
        pytest.param(f2(number="2026<1"), "number", id="number-angle-bracket"),
        pytest.param(f2(number="FACTURA-Ñ1"), "number", id="number-non-ascii"),
        pytest.param(f2(number=" 2026-1"), "number", id="number-leading-space"),
        pytest.param(f2(issue_date="2024-10-27"), "issue_date", id="date-before-verifactu"),
        pytest.param(f2(issue_date="2100-01-01"), "issue_date", id="date-in-the-future"),
        pytest.param(f2(type="F3"), "type", id="type-out-of-scope"),
        pytest.param(f2(description=""), "description", id="description-empty"),
        pytest.param(f2(description="x" * 501), "description", id="description-too-long"),
        pytest.param(f2(tax_lines=[]), "tax_lines", id="no-tax-lines"),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": "1.00", "tax": "0.21"}] * 13),
            "tax_lines",
            id="thirteen-tax-lines",
        ),
        pytest.param(
            f2(
                tax_lines=[
                    {"rate": "21.00", "base": "41.32", "tax": "8.68"},
                    {"rate": "21.00", "base": "41.32", "tax": "8.68"},
                ]
            ),
            "tax_lines",
            id="duplicate-rate",
        ),
        pytest.param(
            f2(tax_lines=[{"rate": "7.50", "base": "100.00", "tax": "7.50"}], total="107.50"),
            "tax_lines.0.rate",
            id="rate-out-of-scope",
        ),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": "82.64", "tax": "17.38"}], total="100.02"),
            "tax_lines.0",
            id="tax-off-by-two-cents",
        ),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": "82.645", "tax": "17.36"}]),
            "tax_lines.0.base",
            id="amount-with-three-decimals",
        ),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": 82.64, "tax": "17.36"}]),
            "tax_lines.0.base",
            id="amount-as-float",
        ),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": "-82.64", "tax": "-17.36"}], total="-100.00"),
            "tax_lines",
            id="negative-line-on-f2",
        ),
        pytest.param(f2(total="100.01"), "total", id="total-mismatch"),
        pytest.param(
            f2(tax_lines=[{"rate": "21.00", "base": "2479.35", "tax": "520.66"}], total="3000.01"),
            "total",
            id="f2-over-aeat-limit",
        ),
        pytest.param(
            f2(recipient={"name": "ACME SL", "nif": "A1234567D"}),
            "recipient",
            id="f2-with-recipient",
        ),
        pytest.param(f2(type="F1"), "recipient", id="f1-without-recipient"),
        pytest.param(r1(type="R5"), "recipient", id="r5-with-recipient"),
        pytest.param(r1(rectifies=[]), "rectifies", id="r1-without-rectified-invoice"),
        pytest.param(
            f1(rectifies=[{"number": "2026-000100", "issue_date": "2026-01-02"}]),
            "rectifies",
            id="f1-with-rectified-invoice",
        ),
        pytest.param(f2(unexpected="x"), "unexpected", id="unknown-field"),
    ],
)
def test_invalid_invoice(data: dict[str, Any], location: str) -> None:
    with pytest.raises(ValidationError) as exc:
        InvoiceAlta.model_validate(data)
    assert any(loc == location or loc.startswith(location) for loc in error_locations(exc)), (
        error_locations(exc)
    )


@pytest.mark.parametrize(
    "recipient",
    [
        pytest.param({"name": "ACME", "nif": "A1234567X"}, id="nif-checksum"),
        pytest.param({"name": "", "nif": "A1234567D"}, id="name-empty"),
        pytest.param(
            {"name": "ACME", "nif": "A1234567D", "country": "FR", "id_type": "02", "id": "FR1"},
            id="nif-and-foreign-id",
        ),
        pytest.param({"name": "ACME"}, id="no-identifier"),
        pytest.param(
            {"name": "ACME", "country": "ES", "id_type": "02", "id": "ESB12345674"},
            id="spain-must-use-nif",
        ),
        pytest.param(
            {"name": "ACME", "country": "US", "id_type": "02", "id": "US123"}, id="not-eu"
        ),
        pytest.param(
            {"name": "ACME", "country": "FR", "id_type": "02", "id": "DE123456789"},
            id="prefix-mismatch",
        ),
        pytest.param(
            {"name": "ACME", "country": "FR", "id_type": "03", "id": "FR123"},
            id="id-type-out-of-scope",
        ),
        pytest.param(
            {"name": "ACME", "country": "FR", "id_type": "02", "id": "FR" + "1" * 19},
            id="id-too-long",
        ),
    ],
)
def test_invalid_recipient(recipient: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Recipient.model_validate(recipient)


# --- Corrections (AEAT validations doc, section 6.1) ----------------------------------------


@pytest.mark.parametrize(
    ("correction", "subsanacion", "rechazo_previo"),
    [
        (Correction.NONE, None, None),
        (Correction.SUBSANACION, "S", None),
        (Correction.AFTER_REJECTED_ALTA, "S", "X"),
        (Correction.AFTER_REJECTED_SUBSANACION, "S", "S"),
    ],
)
def test_correction_flags(
    correction: Correction, subsanacion: str | None, rechazo_previo: str | None
) -> None:
    alta = InvoiceAlta.model_validate(f2(correction=correction))
    assert (alta.subsanacion, alta.rechazo_previo) == (subsanacion, rechazo_previo)


# --- Anulación, chain link, sistema informático -------------------------------------------


def test_anulacion_has_no_minimum_date() -> None:
    # The official test vectors use 2024 dates; only altas have the 28/10/2024 floor.
    anulacion = InvoiceAnulacion(
        issuer_nif="89890001K", number="12345679/G34", issue_date=date(2024, 1, 1)
    )
    assert anulacion.number == "12345679/G34"


def test_anulacion_rejects_bad_number() -> None:
    with pytest.raises(ValidationError):
        InvoiceAnulacion(issuer_nif="89890001K", number="a=b", issue_date=date(2026, 1, 1))


@pytest.mark.parametrize("huella", [CASE_2.lower(), CASE_2[:-1], "G" * 64])
def test_chain_link_requires_64_uppercase_hex(huella: str) -> None:
    with pytest.raises(ValidationError):
        ChainLink(number="2026-1", issue_date=date(2026, 1, 1), huella=huella)


def test_sistema_informatico_defaults_match_spec() -> None:
    sif = SistemaInformatico(
        producer_name="SAMUIL VINITSIY PETROV",
        producer_nif="X1234567L",
        version="1.0.0",
        installation_number="HU-000123",
    )
    assert (sif.name, sif.id) == ("Huella", "HU")
    assert (sif.only_verifactu, sif.multi_ot, sif.multiple_ot_indicator) == ("S", "S", "N")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"id": "hu"}, id="id-lowercase"),
        pytest.param({"id": "ÑU"}, id="id-enye"),
        pytest.param({"id": "H"}, id="id-one-char"),
        pytest.param({"producer_nif": "X1234567A"}, id="producer-nif"),
        pytest.param({"name": "N" * 31}, id="name-too-long"),
        pytest.param({"installation_number": ""}, id="installation-empty"),
    ],
)
def test_invalid_sistema_informatico(overrides: dict[str, str]) -> None:
    data = {
        "producer_name": "SAMUIL VINITSIY PETROV",
        "producer_nif": "X1234567L",
        "version": "1.0.0",
        "installation_number": "HU-000123",
    } | overrides
    with pytest.raises(ValidationError):
        SistemaInformatico.model_validate(data)


# --- hash_record ------------------------------------------------------------------------------


def test_hash_record_alta_uses_the_exact_formatted_values() -> None:
    alta = InvoiceAlta.model_validate(f2())
    previous = ChainLink(number="2026-000122", issue_date=date(2026, 1, 20), huella=CASE_2)
    expected = huella_alta(
        nif="B12345674",
        num="2026-000123",
        fecha="20-01-2026",
        tipo="F2",
        cuota="17.36",
        importe="100.00",
        previa=CASE_2,
        ts="2026-01-20T10:15:03+01:00",
    )
    assert hash_record(alta, previous=previous, ts="2026-01-20T10:15:03+01:00") == expected


def test_hash_record_first_alta_has_empty_previous() -> None:
    alta = InvoiceAlta.model_validate(f2())
    ts = "2026-01-20T10:15:03+01:00"
    assert hash_record(alta, previous=None, ts=ts) == huella_alta(
        nif="B12345674", num="2026-000123", fecha="20-01-2026", tipo="F2",
        cuota="17.36", importe="100.00", previa=None, ts=ts,
    )  # fmt: skip


def test_hash_record_anulacion_matches_official_case_3() -> None:
    anulacion = InvoiceAnulacion(
        issuer_nif="89890001K", number="12345679/G34", issue_date=date(2024, 1, 1)
    )
    previous = ChainLink(number="12345679/G34", issue_date=date(2024, 1, 1), huella=CASE_2)
    assert hash_record(anulacion, previous=previous, ts="2024-01-01T19:20:40+01:00") == CASE_3
    assert huella_anulacion(
        nif="89890001K", num="12345679/G34", fecha="01-01-2024", previa=CASE_2,
        ts="2024-01-01T19:20:40+01:00",
    ) == CASE_3  # fmt: skip


@pytest.mark.parametrize(
    "ts", ["2026-01-20T09:15:03Z", "2026-01-20T10:15:03", "2026-01-20 10:15:03+01:00"]
)
def test_hash_record_rejects_timestamps_not_made_by_timestamp_madrid(ts: str) -> None:
    alta = InvoiceAlta.model_validate(f2())
    with pytest.raises(ValueError, match="timestamp"):
        hash_record(alta, previous=None, ts=ts)
