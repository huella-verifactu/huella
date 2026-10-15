"""XML builders: every document is validated against the official AEAT XSD (SPEC 3.8)."""

from datetime import date
from typing import Any

import pytest
from lxml import etree

from huella.errors import SchemaError
from huella.hash import hash_record
from huella.models import ChainLink, Correction, InvoiceAlta, InvoiceAnulacion, SistemaInformatico
from huella.xml import NS_LR, NS_SF, NS_SOAP, envelope, registro_alta, registro_anulacion, to_bytes

TS = "2026-01-20T10:15:03+01:00"
PREVIOUS = ChainLink(
    number="2026-000122",
    issue_date=date(2026, 1, 20),
    huella="F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97",
)
SIF = SistemaInformatico(
    producer_name="SAMUIL VINITSIY PETROV",
    producer_nif="X1234567L",
    version="0.1.0",
    installation_number="HU-000123",
)
ALTA_ORDER = [
    "IDVersion",
    "IDFactura",
    "NombreRazonEmisor",
    "TipoFactura",
    "DescripcionOperacion",
    "Desglose",
    "CuotaTotal",
    "ImporteTotal",
    "Encadenamiento",
    "SistemaInformatico",
    "FechaHoraHusoGenRegistro",
    "TipoHuella",
    "Huella",
]


def f2(**overrides: Any) -> InvoiceAlta:
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
    return InvoiceAlta.model_validate(data | overrides)


def build(alta: InvoiceAlta, previous: ChainLink | None = PREVIOUS) -> etree._Element:
    return registro_alta(
        alta, previous=previous, ts=TS, huella=hash_record(alta, previous=previous, ts=TS), sif=SIF
    )


def text(element: etree._Element, path: str) -> str | None:
    found = element.find(path, namespaces={"sf": NS_SF})
    return None if found is None else found.text


def local_names(element: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in element]


# --- RegistroAlta ------------------------------------------------------------------------------


def test_simplified_invoice_has_the_xsd_order_and_exact_values() -> None:
    alta = f2()
    element = build(alta)
    assert etree.QName(element).namespace == NS_SF
    assert local_names(element) == ALTA_ORDER
    assert text(element, "sf:IDVersion") == "1.0"
    assert text(element, "sf:IDFactura/sf:FechaExpedicionFactura") == "20-01-2026"
    detalle = "sf:Desglose/sf:DetalleDesglose/"
    assert [text(element, detalle + n) for n in ("sf:Impuesto", "sf:ClaveRegimen")] == ["01", "01"]
    assert text(element, detalle + "sf:CalificacionOperacion") == "S1"
    assert text(element, detalle + "sf:TipoImpositivo") == "21.00"
    assert text(element, detalle + "sf:BaseImponibleOimporteNoSujeto") == "82.64"
    assert text(element, detalle + "sf:CuotaRepercutida") == "17.36"
    assert text(element, "sf:CuotaTotal") == "17.36"
    assert text(element, "sf:ImporteTotal") == "100.00"
    assert text(element, "sf:FechaHoraHusoGenRegistro") == TS
    assert text(element, "sf:TipoHuella") == "01"
    assert text(element, "sf:Huella") == hash_record(alta, previous=PREVIOUS, ts=TS)


def test_chained_record_names_the_previous_one() -> None:
    element = build(f2())
    anterior = "sf:Encadenamiento/sf:RegistroAnterior/"
    assert text(element, anterior + "sf:IDEmisorFactura") == "B12345674"
    assert text(element, anterior + "sf:NumSerieFactura") == "2026-000122"
    assert text(element, anterior + "sf:FechaExpedicionFactura") == "20-01-2026"
    assert text(element, anterior + "sf:Huella") == PREVIOUS.huella


def test_first_record_of_the_chain() -> None:
    element = build(f2(), previous=None)
    assert text(element, "sf:Encadenamiento/sf:PrimerRegistro") == "S"
    assert element.find("sf:Encadenamiento/sf:RegistroAnterior", {"sf": NS_SF}) is None


def test_sistema_informatico_block() -> None:
    element = build(f2())
    sif = element.find("sf:SistemaInformatico", {"sf": NS_SF})
    assert sif is not None
    assert [child.text for child in sif] == [
        "SAMUIL VINITSIY PETROV", "X1234567L", "Huella", "HU", "0.1.0", "HU-000123", "S", "S", "N",
    ]  # fmt: skip


def test_full_invoice_with_spanish_recipient() -> None:
    element = build(f2(type="F1", recipient={"name": "ACME SL", "nif": "A1234567D"}))
    destinatario = "sf:Destinatarios/sf:IDDestinatario/"
    assert text(element, destinatario + "sf:NombreRazon") == "ACME SL"
    assert text(element, destinatario + "sf:NIF") == "A1234567D"


def test_full_invoice_with_eu_recipient() -> None:
    eu = {"name": "ACME SAS", "country": "FR", "id_type": "02", "id": "FR12345678901"}
    element = build(f2(type="F1", recipient=eu))
    otro = "sf:Destinatarios/sf:IDDestinatario/sf:IDOtro/"
    assert [text(element, otro + n) for n in ("sf:CodigoPais", "sf:IDType", "sf:ID")] == [
        "FR",
        "02",
        "FR12345678901",
    ]


def test_corrective_invoice_por_diferencias() -> None:
    alta = f2(
        type="R5",
        number="2026-R-0007",
        tax_lines=[{"rate": "21.00", "base": "-41.32", "tax": "-8.68"}],
        total="-50.00",
        rectifies=[{"number": "2026-000100", "issue_date": "2026-01-02"}],
    )
    element = build(alta)
    assert text(element, "sf:TipoRectificativa") == "I"
    rectificada = "sf:FacturasRectificadas/sf:IDFacturaRectificada/"
    assert text(element, rectificada + "sf:IDEmisorFactura") == "B12345674"
    assert text(element, rectificada + "sf:NumSerieFactura") == "2026-000100"
    assert text(element, rectificada + "sf:FechaExpedicionFactura") == "02-01-2026"
    assert element.find("sf:ImporteRectificacion", {"sf": NS_SF}) is None
    assert text(element, "sf:ImporteTotal") == "-50.00"


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
    element = build(f2(correction=correction))
    assert text(element, "sf:Subsanacion") == subsanacion
    assert text(element, "sf:RechazoPrevio") == rechazo_previo


def test_special_characters_are_escaped_not_altered() -> None:
    alta = f2(number="FAC&2026/1", issuer_name="SMITH & SONS <ES> SL")
    element = build(alta)
    assert text(element, "sf:IDFactura/sf:NumSerieFactura") == "FAC&2026/1"
    assert b"SMITH &amp; SONS &lt;ES&gt; SL" in to_bytes(element)


def test_wrong_huella_is_refused() -> None:
    with pytest.raises(ValueError, match="huella"):
        registro_alta(f2(), previous=PREVIOUS, ts=TS, huella="0" * 64, sif=SIF)


# --- RegistroAnulacion -------------------------------------------------------------------------


def test_anulacion() -> None:
    anulacion = InvoiceAnulacion(
        issuer_nif="B12345674", number="2026-000123", issue_date=date(2026, 1, 20)
    )
    huella = hash_record(anulacion, previous=PREVIOUS, ts=TS)
    element = registro_anulacion(anulacion, previous=PREVIOUS, ts=TS, huella=huella, sif=SIF)
    assert local_names(element) == [
        "IDVersion", "IDFactura", "Encadenamiento", "SistemaInformatico",
        "FechaHoraHusoGenRegistro", "TipoHuella", "Huella",
    ]  # fmt: skip
    assert text(element, "sf:IDFactura/sf:IDEmisorFacturaAnulada") == "B12345674"
    assert text(element, "sf:IDFactura/sf:NumSerieFacturaAnulada") == "2026-000123"
    assert text(element, "sf:IDFactura/sf:FechaExpedicionFacturaAnulada") == "20-01-2026"
    assert text(element, "sf:Huella") == huella


def test_anulacion_with_wrong_huella_is_refused() -> None:
    anulacion = InvoiceAnulacion(
        issuer_nif="B12345674", number="2026-000123", issue_date=date(2026, 1, 20)
    )
    with pytest.raises(ValueError, match="huella"):
        registro_anulacion(anulacion, previous=None, ts=TS, huella="A" * 64, sif=SIF)


# --- Envelope ----------------------------------------------------------------------------------


def test_envelope_with_alta_and_anulacion_validates() -> None:
    alta = build(f2())
    anulacion_model = InvoiceAnulacion(
        issuer_nif="B12345674", number="2026-000100", issue_date=date(2026, 1, 2)
    )
    link = ChainLink(
        number="2026-000123", issue_date=date(2026, 1, 20), huella=text(alta, "sf:Huella") or ""
    )
    anulacion = registro_anulacion(
        anulacion_model,
        previous=link,
        ts=TS,
        huella=hash_record(anulacion_model, previous=link, ts=TS),
        sif=SIF,
    )
    xml = envelope(
        obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[alta, to_bytes(anulacion)]
    )
    root = etree.fromstring(xml)
    assert etree.QName(root).namespace == NS_SOAP
    body = root.find(f"{{{NS_SOAP}}}Body/{{{NS_LR}}}RegFactuSistemaFacturacion")
    assert body is not None
    assert local_names(body) == ["Cabecera", "RegistroFactura", "RegistroFactura"]
    obligado = body.find(f"{{{NS_LR}}}Cabecera/{{{NS_SF}}}ObligadoEmision")
    assert obligado is not None
    assert [child.text for child in obligado] == ["TIENDA EJEMPLO SL", "B12345674"]
    assert xml.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_envelope_accepts_records_stored_as_text() -> None:
    stored = to_bytes(build(f2())).decode()
    assert envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[stored])


@pytest.mark.parametrize("count", [0, 1001])
def test_envelope_needs_1_to_1000_records(count: int) -> None:
    record = to_bytes(build(f2()))
    with pytest.raises(ValueError, match="1000"):
        envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[record] * count)


def test_envelope_records_must_belong_to_the_obligado() -> None:
    with pytest.raises(ValueError, match="obligado"):
        envelope(obligado=("OTRA SL", "A1234567D"), registros=[build(f2())])


def test_envelope_refuses_an_invalid_record() -> None:
    bogus = to_bytes(build(f2())).replace(b"<sf:TipoHuella>01</sf:TipoHuella>", b"")
    with pytest.raises(SchemaError, match=r"TipoHuella|Huella"):
        envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[bogus])


def test_envelope_refuses_entities_in_stored_records() -> None:
    evil = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    with pytest.raises((SchemaError, ValueError)):
        envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[evil])


def test_envelope_refuses_stored_text_that_is_not_a_record() -> None:
    with pytest.raises(ValueError, match="RegistroAlta"):
        envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[b"<Factura/>"])
