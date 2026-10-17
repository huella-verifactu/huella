"""The AEAT consulta service (SPEC 3.9): which records the AEAT holds for an obligado.

``ConsultaFactuSistemaFacturacion`` returns, for one obligado and month, every record the AEAT
holds, with its state and its huella. Huella Cloud uses it to:

1. recover records stuck in ``sending`` (did the request arrive? is the huella ours?),
2. reconcile a chain after a database restore,
3. check the production connection without registering a real invoice.

Pure: :func:`consulta_envelope` builds the request (validated against ``ConsultaLR.xsd``) and
:func:`parse_consulta` reads the answer. Sending it is :meth:`huella.aeat.AeatClient.consulta`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from lxml import etree

from huella._soap import fault, parse_xml
from huella.errors import TransportError
from huella.format import format_date
from huella.xml import AEAT_WS, ID_VERSION, NS_SF, NS_SOAP, sf_element, validate

NS_CONSULTA = AEAT_WS + "ConsultaLR.xsd"
NS_RESPUESTA = AEAT_WS + "RespuestaConsultaLR.xsd"
_NS = {"rc": NS_RESPUESTA, "sf": NS_SF}


class HeldState(StrEnum):
    """``EstadoRegistro`` of a record the AEAT holds."""

    ACCEPTED = "Correcto"
    ACCEPTED_WITH_ERRORS = "AceptadoConErrores"
    CANCELLED = "Anulado"


@dataclass(frozen=True)
class PageKey:
    """``ClavePaginacion``: where the next page starts."""

    issuer_nif: str
    number: str
    issue_date: date


@dataclass(frozen=True)
class HeldRecord:
    """One record as the AEAT holds it. Amounts and the huella are the exact strings."""

    issuer_nif: str
    number: str
    issue_date: date
    state: HeldState
    huella: str | None
    generated_at: str | None  # FechaHoraHusoGenRegistro, as sent
    invoice_type: str | None
    total: str | None
    tax_total: str | None
    subsanacion: bool
    error_code: int | None
    error_message: str | None


@dataclass(frozen=True)
class ConsultaResult:
    found: bool  # ResultadoConsulta: ConDatos / SinDatos
    records: tuple[HeldRecord, ...]
    next_page: PageKey | None  # set when IndicadorPaginacion = S
    raw: bytes


# --- Request -------------------------------------------------------------------------------------


def consulta_envelope(  # noqa: PLR0913 - every argument is one optional filter of the query
    *,
    obligado: tuple[str, str],
    year: int,
    month: int,
    number: str | None = None,
    issue_date: date | None = None,
    page: PageKey | None = None,
) -> bytes:
    """SOAP request for the records of ``obligado`` (``(legal name, NIF)``) in one month.

    ``number`` and ``issue_date`` narrow it to one invoice; ``page`` asks for the next page of
    an earlier answer. The month is the *imputation* period: the issue date's month.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1 to 12, got {month}")
    name, nif = obligado
    root = etree.Element(
        f"{{{NS_SOAP}}}Envelope", nsmap={"soapenv": NS_SOAP, "con": NS_CONSULTA, "sf": NS_SF}
    )
    etree.SubElement(root, f"{{{NS_SOAP}}}Header")
    body = etree.SubElement(root, f"{{{NS_SOAP}}}Body")
    request = etree.SubElement(body, f"{{{NS_CONSULTA}}}ConsultaFactuSistemaFacturacion")
    header = etree.SubElement(request, f"{{{NS_CONSULTA}}}Cabecera")
    sf_element(header, "IDVersion", ID_VERSION)
    obligado_emision = sf_element(header, "ObligadoEmision")
    sf_element(obligado_emision, "NombreRazon", name)
    sf_element(obligado_emision, "NIF", nif)
    filters = etree.SubElement(request, f"{{{NS_CONSULTA}}}FiltroConsulta")
    # Elements declared in ConsultaLR.xsd are in its namespace; their contents (types from
    # SuministroInformacion.xsd) are in sf. The XSD check below enforces exactly this.
    period = etree.SubElement(filters, f"{{{NS_CONSULTA}}}PeriodoImputacion")
    sf_element(period, "Ejercicio", f"{year:04d}")
    sf_element(period, "Periodo", f"{month:02d}")
    if number is not None:
        etree.SubElement(filters, f"{{{NS_CONSULTA}}}NumSerieFactura").text = number
    if issue_date is not None:
        dates = etree.SubElement(filters, f"{{{NS_CONSULTA}}}FechaExpedicionFactura")
        sf_element(dates, "FechaExpedicionFactura", format_date(issue_date))
    if page is not None:
        key = etree.SubElement(filters, f"{{{NS_CONSULTA}}}ClavePaginacion")
        sf_element(key, "IDEmisorFactura", page.issuer_nif)
        sf_element(key, "NumSerieFactura", page.number)
        sf_element(key, "FechaExpedicionFactura", format_date(page.issue_date))
    validate(request, "ConsultaLR.xsd")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


# --- Answer --------------------------------------------------------------------------------------


def _text(element: etree._Element, path: str) -> str | None:
    text = element.findtext(path, namespaces=_NS)
    return None if text is None else text.strip()


def _required(element: etree._Element, path: str) -> str:
    text = _text(element, path)
    if text is None:
        raise TransportError(f"unexpected consulta answer: {path} missing")
    return text


def _date(text: str) -> date:
    return datetime.strptime(text, "%d-%m-%Y").date()  # noqa: DTZ007 - a calendar date


def _record(item: etree._Element) -> HeldRecord:
    data = "rc:DatosRegistroFacturacion/rc:"
    code = _text(item, "rc:EstadoRegistro/rc:CodigoErrorRegistro")
    return HeldRecord(
        issuer_nif=_required(item, "rc:IDFactura/sf:IDEmisorFactura"),
        number=_required(item, "rc:IDFactura/sf:NumSerieFactura"),
        issue_date=_date(_required(item, "rc:IDFactura/sf:FechaExpedicionFactura")),
        state=HeldState(_required(item, "rc:EstadoRegistro/rc:EstadoRegistro")),
        huella=_text(item, data + "Huella"),
        generated_at=_text(item, data + "FechaHoraHusoGenRegistro"),
        invoice_type=_text(item, data + "TipoFactura"),
        total=_text(item, data + "ImporteTotal"),
        tax_total=_text(item, data + "CuotaTotal"),
        subsanacion=_text(item, data + "Subsanacion") == "S",
        error_code=None if code is None else int(code),
        error_message=_text(item, "rc:EstadoRegistro/rc:DescripcionErrorRegistro"),
    )


def _page(response: etree._Element) -> PageKey | None:
    if _text(response, "rc:IndicadorPaginacion") != "S":
        return None
    return PageKey(
        issuer_nif=_required(response, "rc:ClavePaginacion/sf:IDEmisorFactura"),
        number=_required(response, "rc:ClavePaginacion/sf:NumSerieFactura"),
        issue_date=_date(_required(response, "rc:ClavePaginacion/sf:FechaExpedicionFactura")),
    )


def parse_consulta(body: bytes) -> ConsultaResult:
    """Parse an answer to ``ConsultaFactuSistemaFacturacion``. Raises on faults and bad bodies."""
    root = parse_xml(body)
    soap_fault = root.find(f"{{{NS_SOAP}}}Body/{{{NS_SOAP}}}Fault")
    if soap_fault is not None:
        raise fault(soap_fault)
    response = root.find(
        f"{{{NS_SOAP}}}Body/{{{NS_RESPUESTA}}}RespuestaConsultaFactuSistemaFacturacion"
    )
    if response is None:
        raise TransportError(
            "unexpected consulta answer: no RespuestaConsultaFactuSistemaFacturacion"
        )
    try:
        items = response.iterfind("rc:RegistroRespuestaConsultaFactuSistemaFacturacion", _NS)
        return ConsultaResult(
            found=_required(response, "rc:ResultadoConsulta") == "ConDatos",
            records=tuple(_record(item) for item in items),
            next_page=_page(response),
            raw=body,
        )
    except ValueError as exc:
        raise TransportError(f"unexpected consulta answer: {exc}") from exc
