"""Billing record models with every validation rule that is in v1 scope (SPEC 3.3).

A model that validates is a record the AEAT will accept, as far as the rules can be checked
locally. Sources: SPEC 3.3, ``SuministroInformacion.xsd`` and the AEAT validations document
(``Validaciones_Errores_Veri-Factu.pdf``, sections 3.1.3 and 6.1).

Amounts are ``Decimal`` with at most two decimals. They may arrive as strings (API JSON) but never
as ``float``. Models are immutable.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from huella.format import MADRID, format_amount, round_amount
from huella.nif import validate_nif

VERIFACTU_START = date(2024, 10, 28)  # Orden HAC/1177/2024 in force; AEAT rejects older dates
SIMPLIFIED_INVOICE_MAX = Decimal("3000.00")  # AEAT check on F2 totals (validations 15.8)
# Per tax line. Shops that round tax per order line (WooCommerce's default) drift by up to
# half a cent per line, so 0.01 refused real invoices. 1.00 is still ten times stricter than
# the AEAT's 10.00; wrong-rate bugs are caught by SUPPORTED_RATES (decided 16 Oct, SPEC 3.3).
TAX_TOLERANCE = Decimal("1.00")
SUPPORTED_RATES = (Decimal("21"), Decimal("10"), Decimal("4"))  # v1 scope (SPEC 1.1)
MAX_TAX_LINES = 12  # XSD DesgloseType
_NUMBER_FORBIDDEN = frozenset("\"'<>=")
_CENT = Decimal("0.01")

# EU member states other than Spain -> prefix of their VAT numbers (Greece uses EL).
EU_VAT_PREFIXES = {
    "AT": "AT", "BE": "BE", "BG": "BG", "CY": "CY", "CZ": "CZ", "DE": "DE", "DK": "DK",
    "EE": "EE", "FI": "FI", "FR": "FR", "GR": "EL", "HR": "HR", "HU": "HU", "IE": "IE",
    "IT": "IT", "LT": "LT", "LU": "LU", "LV": "LV", "MT": "MT", "NL": "NL", "PL": "PL",
    "PT": "PT", "RO": "RO", "SE": "SE", "SI": "SI", "SK": "SK",
}  # fmt: skip


# --- Field types -----------------------------------------------------------------------------


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("amounts must be strings or Decimal, never float")
    return value


def _exact_cents(value: Decimal) -> Decimal:
    format_amount(value)  # raises ValueError if it cannot be written exactly with 2 decimals
    return value


def check_invoice_number(value: str) -> str:
    """Return ``value`` if the AEAT accepts it as ``NumSerieFactura``, else raise ``ValueError``."""
    if not 1 <= len(value) <= 60:
        raise ValueError("must be 1 to 60 characters")
    if value != value.strip():
        raise ValueError("must not start or end with spaces")
    rejected = {c for c in value if not 32 <= ord(c) <= 126 or c in _NUMBER_FORBIDDEN}
    if rejected:
        raise ValueError(f"contains characters the AEAT rejects: {''.join(sorted(rejected))!r}")
    return value


def _check_alta_date(value: date) -> date:
    if value < VERIFACTU_START:
        raise ValueError(f"must not be before {VERIFACTU_START.isoformat()}")
    if value > datetime.now(MADRID).date():
        raise ValueError("must not be in the future (Madrid date)")
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float), AfterValidator(_exact_cents)]
Nif = Annotated[str, AfterValidator(validate_nif)]
InvoiceNumber = Annotated[str, AfterValidator(check_invoice_number)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Huella = Annotated[str, StringConstraints(pattern=r"^[0-9A-F]{64}$")]
InvoiceType = Literal["F1", "F2", "R1", "R4", "R5"]

WITH_RECIPIENT: frozenset[str] = frozenset({"F1", "R1", "R4"})
CORRECTIVE: frozenset[str] = frozenset({"R1", "R4", "R5"})


class Environment(StrEnum):
    """AEAT environment. Test and production are separate systems, each with its own chain."""

    TEST = "test"  # AEAT pre-production (Portal de Pruebas Externas)
    PRODUCTION = "production"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Parts of a record -----------------------------------------------------------------------


class TaxLine(_Model):
    """One VAT rate of the invoice (``DetalleDesglose``)."""

    rate: Annotated[Decimal, BeforeValidator(_reject_float)]
    base: Money
    tax: Money

    @field_validator("rate")
    @classmethod
    def _supported_rate(cls, rate: Decimal) -> Decimal:
        if rate not in SUPPORTED_RATES:
            raise ValueError("only 21, 10 and 4 % VAT are supported in v1")
        return rate.quantize(_CENT)

    @model_validator(mode="after")
    def _tax_matches_rate(self) -> Self:
        expected = round_amount(self.base * self.rate / 100)
        if abs(self.tax - expected) > TAX_TOLERANCE:
            raise ValueError(
                f"tax {self.tax} should be {expected} ± {TAX_TOLERANCE} "
                f"for {self.rate}% of {self.base}"
            )
        return self


class Recipient(_Model):
    """The customer (``IDDestinatario``): a Spanish NIF, or an EU VAT number (``IDOtro`` 02)."""

    name: Name
    nif: Nif | None = None
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    id_type: Literal["02"] | None = None
    id: Annotated[str, StringConstraints(min_length=1, max_length=20)] | None = None

    @model_validator(mode="after")
    def _one_identifier(self) -> Self:
        foreign = (self.country, self.id_type, self.id)
        if self.nif is not None:
            if any(part is not None for part in foreign):
                raise ValueError("give either nif, or country + id_type + id, not both")
            return self
        if self.country is None or self.id_type is None or self.id is None:
            raise ValueError("a recipient needs a Spanish nif, or country + id_type + id")
        prefix = EU_VAT_PREFIXES.get(self.country)
        if prefix is None:
            raise ValueError(
                f"{self.country} is not an EU member state other than Spain "
                "(Spanish recipients use nif)"
            )
        if not re.fullmatch(prefix + r"[0-9A-Z+*]{2,12}", self.id):
            raise ValueError(f"an EU VAT number from {self.country} starts with {prefix}")
        return self


class Rectification(_Model):
    """An invoice corrected by an R1/R4/R5 (``IDFacturaRectificada``); same issuer."""

    number: InvoiceNumber
    issue_date: date


class Correction(StrEnum):
    """Which kind of alta this is (AEAT validations doc, 6.1).

    ===============================  ===========  ==============
    Situation                        Subsanacion  RechazoPrevio
    ===============================  ===========  ==============
    NONE: normal alta                (omitted)    (omitted)
    SUBSANACION: fix of a record     S            (omitted)
    the AEAT holds
    AFTER_REJECTED_ALTA: the         S            X
    original alta was rejected
    AFTER_REJECTED_SUBSANACION: a    S            S
    previous fix was rejected
    ===============================  ===========  ==============
    """

    NONE = "none"
    SUBSANACION = "subsanacion"
    AFTER_REJECTED_ALTA = "after_rejected_alta"
    AFTER_REJECTED_SUBSANACION = "after_rejected_subsanacion"


_RECHAZO_PREVIO = {
    Correction.AFTER_REJECTED_ALTA: "X",
    Correction.AFTER_REJECTED_SUBSANACION: "S",
}


# --- Records ---------------------------------------------------------------------------------


class InvoiceAlta(_Model):
    """A *registro de alta*: an issued invoice.

    Field order matters: later validators read earlier fields from ``info.data``.
    """

    issuer_nif: Nif
    issuer_name: Name
    number: InvoiceNumber
    issue_date: Annotated[date, AfterValidator(_check_alta_date)]
    type: InvoiceType
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    tax_lines: Annotated[tuple[TaxLine, ...], Field(min_length=1, max_length=MAX_TAX_LINES)]
    total: Money
    recipient: Recipient | None = Field(default=None, validate_default=True)
    rectifies: Annotated[tuple[Rectification, ...], Field(max_length=1000)] = Field(
        default=(), validate_default=True
    )
    correction: Correction = Correction.NONE

    @field_validator("tax_lines")
    @classmethod
    def _one_line_per_rate(
        cls, lines: tuple[TaxLine, ...], info: ValidationInfo
    ) -> tuple[TaxLine, ...]:
        rates = [line.rate for line in lines]
        if len(set(rates)) != len(rates):
            raise ValueError("use one line per VAT rate")
        invoice_type = info.data.get("type")
        if invoice_type in {"F1", "F2"} and any(line.base < 0 or line.tax < 0 for line in lines):
            raise ValueError(f"{invoice_type} amounts cannot be negative; use a corrective invoice")
        return lines

    @field_validator("total")
    @classmethod
    def _total_is_the_sum(cls, total: Decimal, info: ValidationInfo) -> Decimal:
        lines: tuple[TaxLine, ...] | None = info.data.get("tax_lines")
        if lines is not None:
            expected = sum((line.base + line.tax for line in lines), Decimal(0))
            if total != expected:
                raise ValueError(f"must equal the sum of bases and taxes, {expected}")
        if info.data.get("type") == "F2" and total > SIMPLIFIED_INVOICE_MAX:
            raise ValueError(f"a simplified invoice (F2) cannot exceed {SIMPLIFIED_INVOICE_MAX}")
        return total

    @field_validator("recipient")
    @classmethod
    def _recipient_matches_type(
        cls, recipient: Recipient | None, info: ValidationInfo
    ) -> Recipient | None:
        invoice_type = info.data.get("type")
        if invoice_type in WITH_RECIPIENT and recipient is None:
            raise ValueError(f"{invoice_type} needs a recipient")
        if (
            invoice_type is not None
            and invoice_type not in WITH_RECIPIENT
            and recipient is not None
        ):
            raise ValueError(f"{invoice_type} must not have a recipient")
        return recipient

    @field_validator("rectifies")
    @classmethod
    def _rectifies_matches_type(
        cls, rectifies: tuple[Rectification, ...], info: ValidationInfo
    ) -> tuple[Rectification, ...]:
        invoice_type = info.data.get("type")
        if invoice_type in CORRECTIVE and not rectifies:
            raise ValueError(f"{invoice_type} must name the invoice(s) it corrects")
        if invoice_type is not None and invoice_type not in CORRECTIVE and rectifies:
            raise ValueError(f"{invoice_type} is not a corrective invoice")
        return rectifies

    @property
    def cuota_total(self) -> Decimal:
        """Σ tax of all lines (``CuotaTotal``)."""
        return sum((line.tax for line in self.tax_lines), Decimal(0))

    @property
    def subsanacion(self) -> Literal["S"] | None:
        return None if self.correction is Correction.NONE else "S"

    @property
    def rechazo_previo(self) -> str | None:
        return _RECHAZO_PREVIO.get(self.correction)


class InvoiceAnulacion(_Model):
    """A *registro de anulación*: cancels an invoice issued by mistake (never for refunds)."""

    issuer_nif: Nif
    number: InvoiceNumber
    issue_date: date


class ChainLink(_Model):
    """What the next record needs from the previous one (``RegistroAnterior``)."""

    number: InvoiceNumber
    issue_date: date
    huella: Huella


class SistemaInformatico(_Model):
    """The billing system block sent in every record (SPEC 3.10)."""

    producer_name: Name
    producer_nif: Nif
    name: Annotated[str, StringConstraints(min_length=1, max_length=30)] = "Huella"
    id: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2}$")] = "HU"
    version: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    installation_number: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    only_verifactu: Literal["S"] = "S"
    multi_ot: Literal["S", "N"] = "S"
    multiple_ot_indicator: Literal["S", "N"] = "N"
