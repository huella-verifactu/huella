"""The consulta service (SPEC 3.9): request builder, answer parser, client. No network."""

import ssl
from datetime import date
from pathlib import Path

import httpx
import pytest
from lxml import etree

from huella.aeat import AeatClient
from huella.consulta import (
    NS_CONSULTA,
    NS_RESPUESTA,
    HeldState,
    PageKey,
    consulta_envelope,
    parse_consulta,
)
from huella.errors import AeatFault, TransportError
from huella.models import Environment
from huella.xml import NS_SF, load_schema

FIXTURES = Path(__file__).parent / "fixtures" / "aeat_responses"
OBLIGADO = ("TIENDA EJEMPLO SL", "B12345674")


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize("name", ["consulta_con_datos.xml", "consulta_sin_datos.xml"])
def test_fixture_is_valid_against_the_consulta_response_xsd(name: str) -> None:
    root = etree.fromstring(fixture(name))
    response = root.find(f".//{{{NS_RESPUESTA}}}RespuestaConsultaFactuSistemaFacturacion")
    assert response is not None
    schema = load_schema("RespuestaConsultaLR.xsd")
    assert schema.validate(response), schema.error_log


def _request(envelope: bytes) -> etree._Element:
    root = etree.fromstring(envelope)
    request = root.find(f".//{{{NS_CONSULTA}}}ConsultaFactuSistemaFacturacion")
    assert request is not None
    return request


def test_a_month_of_one_obligado() -> None:
    request = _request(consulta_envelope(obligado=OBLIGADO, year=2026, month=1))
    assert request.findtext(f".//{{{NS_SF}}}NIF") == "B12345674"
    assert request.findtext(f".//{{{NS_SF}}}Ejercicio") == "2026"
    assert request.findtext(f".//{{{NS_SF}}}Periodo") == "01"
    assert request.find(f".//{{{NS_CONSULTA}}}NumSerieFactura") is None


def test_one_invoice_and_the_next_page() -> None:
    page = PageKey("B12345674", "2026-000124", date(2026, 1, 21))
    envelope = consulta_envelope(
        obligado=OBLIGADO,
        year=2026,
        month=1,
        number="2026-000123",
        issue_date=date(2026, 1, 20),
        page=page,
    )
    filters = _request(envelope).find(f"{{{NS_CONSULTA}}}FiltroConsulta")  # XSD-checked
    assert filters is not None
    assert filters.findtext(f"{{{NS_CONSULTA}}}NumSerieFactura") == "2026-000123"
    dates = filters.find(f"{{{NS_CONSULTA}}}FechaExpedicionFactura")
    assert dates is not None
    assert dates.findtext(f"{{{NS_SF}}}FechaExpedicionFactura") == "20-01-2026"
    key = filters.find(f"{{{NS_CONSULTA}}}ClavePaginacion")
    assert key is not None
    assert key.findtext(f"{{{NS_SF}}}NumSerieFactura") == "2026-000124"


@pytest.mark.parametrize("month", [0, 13])
def test_months_outside_the_year_are_refused(month: int) -> None:
    with pytest.raises(ValueError, match="month"):
        consulta_envelope(obligado=OBLIGADO, year=2026, month=month)


def test_parse_records_with_their_huella() -> None:
    result = parse_consulta(fixture("consulta_con_datos.xml"))
    assert result.found
    first, second = result.records
    assert (first.number, first.issue_date, first.state) == (
        "2026-000123",
        date(2026, 1, 20),
        HeldState.ACCEPTED,
    )
    assert first.huella == "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60"
    assert (first.invoice_type, first.total, first.tax_total) == ("F2", "100.00", "17.36")
    assert first.generated_at == "2026-01-20T10:15:03+01:00"
    assert (first.subsanacion, first.error_code, first.error_message) == (False, None, None)
    assert (second.state, second.subsanacion, second.error_code) == (
        HeldState.ACCEPTED_WITH_ERRORS,
        True,
        2004,
    )
    assert result.next_page == PageKey("B12345674", "2026-000124", date(2026, 1, 21))


def test_parse_an_empty_month() -> None:
    result = parse_consulta(fixture("consulta_sin_datos.xml"))
    assert (result.found, result.records, result.next_page) == (False, (), None)


def test_a_fault_and_a_strange_body_raise() -> None:
    with pytest.raises(AeatFault):
        parse_consulta(fixture("fault_client.xml"))
    with pytest.raises(TransportError):
        parse_consulta(fixture("correcto.xml"))  # an answer to the other operation
    broken = fixture("consulta_con_datos.xml").replace(b">Correcto<", b">Desconocido<")
    with pytest.raises(TransportError):
        parse_consulta(broken)
    no_number = fixture("consulta_con_datos.xml").replace(
        b"<tik:NumSerieFactura>2026-000123</tik:NumSerieFactura>", b""
    )
    with pytest.raises(TransportError, match="NumSerieFactura"):
        parse_consulta(no_number)


def test_the_client_posts_a_consulta_to_the_same_endpoint() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=fixture("consulta_sin_datos.xml"))

    envelope = consulta_envelope(obligado=OBLIGADO, year=2026, month=2)
    with AeatClient(
        env=Environment.TEST,
        ssl_context=ssl.create_default_context(),
        transport=httpx.MockTransport(answer),
    ) as client:
        result = client.consulta(envelope)
    assert result.found is False
    endpoint = "https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
    assert str(seen[0].url) == endpoint
    assert seen[0].content == envelope


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        (b">S</tikLRRC:IndicadorPaginacion>", b">X</tikLRRC:IndicadorPaginacion>", "Paginacion"),
        (b">ConDatos<", b">Quizas<", "ResultadoConsulta"),
        (b">2026-000123</tik:NumSerieFactura>", b"></tik:NumSerieFactura>", "NumSerieFactura"),
        (
            b"<tikLRRC:TimestampUltimaModificacion>2026-01-20T10:15:05+01:00",
            b"<tikLRRC:X>",
            "Timestamp",
        ),
    ],
)
def test_values_outside_the_schema_are_not_guessed(old: bytes, new: bytes, field: str) -> None:
    body = fixture("consulta_con_datos.xml").replace(old, new, 1)
    if b"<tikLRRC:X>" in body:
        body = body.replace(b"</tikLRRC:TimestampUltimaModificacion>", b"</tikLRRC:X>", 1)
    with pytest.raises(TransportError, match=field):
        parse_consulta(body)


def test_the_last_change_of_each_record_is_kept() -> None:
    first = parse_consulta(fixture("consulta_con_datos.xml")).records[0]
    assert first.last_modified == "2026-01-20T10:15:05+01:00"


def test_a_doctype_is_refused() -> None:
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    with pytest.raises(TransportError, match="DOCTYPE"):
        parse_consulta(evil)
