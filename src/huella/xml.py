"""Build the AEAT XML: RegistroAlta, RegistroAnulacion and the SOAP envelope (SPEC 3.8).

Every builder validates its output against the official XSD before returning, so an invalid
document never leaves the library. A :class:`SchemaError` is therefore always a bug in huella:
bad user input is stopped earlier by :mod:`huella.models`.

Element order follows ``SuministroInformacion.xsd`` exactly; the XSD check proves it. The schemas
load from the bundled files with network access disabled.
"""

import copy
import threading
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from lxml import etree

from huella.errors import SchemaError
from huella.format import format_amount, format_date
from huella.hash import TIPO_HUELLA_SHA256, hash_record
from huella.models import (
    CORRECTIVE,
    ChainLink,
    InvoiceAlta,
    InvoiceAnulacion,
    Recipient,
    SistemaInformatico,
)

NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
AEAT_WS = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/"
    "tike/cont/ws/"
)
NS_LR = AEAT_WS + "SuministroLR.xsd"
NS_SF = AEAT_WS + "SuministroInformacion.xsd"
ID_VERSION = "1.0"
MAX_RECORDS = 1000  # per request, all for one obligado

SPECS = Path(__file__).parent / "specs" / "v1_0"
_XMLDSIG_URL = "http://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd"
_RECORD_TAGS = (f"{{{NS_SF}}}RegistroAlta", f"{{{NS_SF}}}RegistroAnulacion")

# v1 scope (SPEC 1.1): VAT, general regime, subject and not exempt.
IMPUESTO_IVA = "01"
CLAVE_REGIMEN_GENERAL = "01"
CALIFICACION_SUJETA = "S1"
RECTIFICATIVA_POR_DIFERENCIAS = "I"


# --- Schemas -----------------------------------------------------------------------------------


class _BundledSchemas(etree.Resolver):
    """Serve the W3C xmldsig import from the bundled copy instead of the network."""

    def resolve(self, system_url: str, public_id: str, context: object) -> object:  # type: ignore[override]
        if system_url == _XMLDSIG_URL:
            return self.resolve_filename(str(SPECS / "xmldsig-core-schema.xsd"), context)
        return None


_schemas = threading.local()  # lxml validators are not shared between threads


def load_schema(filename: str) -> etree.XMLSchema:
    cache: dict[str, etree.XMLSchema] = _schemas.__dict__.setdefault("cache", {})
    if filename not in cache:
        parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=False)
        parser.resolvers.add(_BundledSchemas())
        cache[filename] = etree.XMLSchema(etree.parse(str(SPECS / filename), parser))
    return cache[filename]


def validate(element: etree._Element, filename: str) -> None:
    """Raise :class:`SchemaError` unless ``element`` is valid against the bundled ``filename``."""
    schema = load_schema(filename)
    if not schema.validate(element):
        raise SchemaError(f"{filename}: {schema.error_log.last_error}")


# --- Small builders ----------------------------------------------------------------------------


def sf_element(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    element = etree.SubElement(parent, f"{{{NS_SF}}}{tag}")
    if text is not None:
        element.text = text
    return element


def _id_factura(parent: etree._Element, tag: str, nif: str, number: str, issued: date) -> None:
    block = sf_element(parent, tag)
    sf_element(block, "IDEmisorFactura", nif)
    sf_element(block, "NumSerieFactura", number)
    sf_element(block, "FechaExpedicionFactura", format_date(issued))


def _destinatario(parent: etree._Element, recipient: Recipient) -> None:
    block = sf_element(sf_element(parent, "Destinatarios"), "IDDestinatario")
    sf_element(block, "NombreRazon", recipient.name)
    if recipient.nif is not None:
        sf_element(block, "NIF", recipient.nif)
        return
    otro = sf_element(block, "IDOtro")
    sf_element(otro, "CodigoPais", recipient.country)
    sf_element(otro, "IDType", recipient.id_type)
    sf_element(otro, "ID", recipient.id)


def _encadenamiento(parent: etree._Element, nif: str, previous: ChainLink | None) -> None:
    block = sf_element(parent, "Encadenamiento")
    if previous is None:
        sf_element(block, "PrimerRegistro", "S")
        return
    anterior = sf_element(block, "RegistroAnterior")
    sf_element(anterior, "IDEmisorFactura", nif)
    sf_element(anterior, "NumSerieFactura", previous.number)
    sf_element(anterior, "FechaExpedicionFactura", format_date(previous.issue_date))
    sf_element(anterior, "Huella", previous.huella)


def _sistema_informatico(parent: etree._Element, sif: SistemaInformatico) -> None:
    block = sf_element(parent, "SistemaInformatico")
    sf_element(block, "NombreRazon", sif.producer_name)
    sf_element(block, "NIF", sif.producer_nif)
    sf_element(block, "NombreSistemaInformatico", sif.name)
    sf_element(block, "IdSistemaInformatico", sif.id)
    sf_element(block, "Version", sif.version)
    sf_element(block, "NumeroInstalacion", sif.installation_number)
    sf_element(block, "TipoUsoPosibleSoloVerifactu", sif.only_verifactu)
    sf_element(block, "TipoUsoPosibleMultiOT", sif.multi_ot)
    sf_element(block, "IndicadorMultiplesOT", sif.multiple_ot_indicator)


def _close(record: etree._Element, sif: SistemaInformatico, ts: str, huella: str) -> None:
    """The fields every record ends with, in XSD order."""
    _sistema_informatico(record, sif)
    sf_element(record, "FechaHoraHusoGenRegistro", ts)
    sf_element(record, "TipoHuella", TIPO_HUELLA_SHA256)
    sf_element(record, "Huella", huella)


def _check_huella(given: str, expected: str) -> None:
    if given != expected:
        raise ValueError(
            f"huella {given} does not match the record ({expected}); compute it with "
            "hash_record() using the same previous link and timestamp"
        )


# --- Records -----------------------------------------------------------------------------------


def registro_alta(
    alta: InvoiceAlta,
    *,
    previous: ChainLink | None,
    ts: str,
    huella: str,
    sif: SistemaInformatico,
) -> etree._Element:
    """The ``RegistroAlta`` element, validated against the XSD.

    ``huella`` must be ``hash_record(alta, previous=previous, ts=ts)``; it is checked.
    """
    _check_huella(huella, hash_record(alta, previous=previous, ts=ts))
    record = etree.Element(f"{{{NS_SF}}}RegistroAlta", nsmap={"sf": NS_SF})
    sf_element(record, "IDVersion", ID_VERSION)
    _id_factura(record, "IDFactura", alta.issuer_nif, alta.number, alta.issue_date)
    sf_element(record, "NombreRazonEmisor", alta.issuer_name)
    if alta.subsanacion is not None:
        sf_element(record, "Subsanacion", alta.subsanacion)
    if alta.rechazo_previo is not None:
        sf_element(record, "RechazoPrevio", alta.rechazo_previo)
    sf_element(record, "TipoFactura", alta.type)
    if alta.type in CORRECTIVE:
        sf_element(record, "TipoRectificativa", RECTIFICATIVA_POR_DIFERENCIAS)
        rectificadas = sf_element(record, "FacturasRectificadas")
        for rectified in alta.rectifies:
            _id_factura(
                rectificadas,
                "IDFacturaRectificada",
                alta.issuer_nif,
                rectified.number,
                rectified.issue_date,
            )
    sf_element(record, "DescripcionOperacion", alta.description)
    if alta.recipient is not None:
        _destinatario(record, alta.recipient)
    desglose = sf_element(record, "Desglose")
    for line in alta.tax_lines:
        detalle = sf_element(desglose, "DetalleDesglose")
        sf_element(detalle, "Impuesto", IMPUESTO_IVA)
        sf_element(detalle, "ClaveRegimen", CLAVE_REGIMEN_GENERAL)
        sf_element(detalle, "CalificacionOperacion", CALIFICACION_SUJETA)
        sf_element(detalle, "TipoImpositivo", format_amount(line.rate))
        sf_element(detalle, "BaseImponibleOimporteNoSujeto", format_amount(line.base))
        sf_element(detalle, "CuotaRepercutida", format_amount(line.tax))
    sf_element(record, "CuotaTotal", format_amount(alta.cuota_total))
    sf_element(record, "ImporteTotal", format_amount(alta.total))
    _encadenamiento(record, alta.issuer_nif, previous)
    _close(record, sif, ts, huella)
    validate(record, "SuministroInformacion.xsd")
    return record


def registro_anulacion(
    anulacion: InvoiceAnulacion,
    *,
    previous: ChainLink | None,
    ts: str,
    huella: str,
    sif: SistemaInformatico,
) -> etree._Element:
    """The ``RegistroAnulacion`` element, validated against the XSD."""
    _check_huella(huella, hash_record(anulacion, previous=previous, ts=ts))
    record = etree.Element(f"{{{NS_SF}}}RegistroAnulacion", nsmap={"sf": NS_SF})
    sf_element(record, "IDVersion", ID_VERSION)
    block = sf_element(record, "IDFactura")
    sf_element(block, "IDEmisorFacturaAnulada", anulacion.issuer_nif)
    sf_element(block, "NumSerieFacturaAnulada", anulacion.number)
    sf_element(block, "FechaExpedicionFacturaAnulada", format_date(anulacion.issue_date))
    _encadenamiento(record, anulacion.issuer_nif, previous)
    _close(record, sif, ts, huella)
    validate(record, "SuministroInformacion.xsd")
    return record


def to_bytes(record: etree._Element) -> bytes:
    """Serialised record, as stored by the cloud (``records.xml``) and later sent unchanged."""
    return etree.tostring(record, encoding="utf-8", xml_declaration=False)


# --- Envelope ----------------------------------------------------------------------------------


def _record_element(record: etree._Element | bytes | str) -> etree._Element:
    if isinstance(record, etree._Element):
        return copy.deepcopy(record)
    data = record.encode() if isinstance(record, str) else record
    parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=False)
    element = etree.fromstring(data, parser)
    if element.getroottree().docinfo.doctype:
        raise ValueError("stored records must not contain a DOCTYPE")
    if element.tag not in _RECORD_TAGS:
        raise ValueError(f"not a RegistroAlta or RegistroAnulacion: {element.tag!r}")
    return element


def envelope(
    *, obligado: tuple[str, str], registros: Sequence[etree._Element | bytes | str]
) -> bytes:
    """SOAP request for ``RegFactuSistemaFacturacion`` with 1 to 1000 records of one obligado.

    ``obligado`` is ``(legal name, NIF)``. Records may be elements or their stored bytes/text.
    """
    if not 1 <= len(registros) <= MAX_RECORDS:
        raise ValueError(f"a request carries 1 to {MAX_RECORDS} records, got {len(registros)}")
    name, nif = obligado
    root = etree.Element(
        f"{{{NS_SOAP}}}Envelope", nsmap={"soapenv": NS_SOAP, "sum": NS_LR, "sf": NS_SF}
    )
    etree.SubElement(root, f"{{{NS_SOAP}}}Header")
    request = etree.SubElement(
        etree.SubElement(root, f"{{{NS_SOAP}}}Body"), f"{{{NS_LR}}}RegFactuSistemaFacturacion"
    )
    obligado_emision = sf_element(
        etree.SubElement(request, f"{{{NS_LR}}}Cabecera"), "ObligadoEmision"
    )
    sf_element(obligado_emision, "NombreRazon", name)
    sf_element(obligado_emision, "NIF", nif)
    for registro in registros:
        element = _record_element(registro)
        issuer = element.findtext(f"{{{NS_SF}}}IDFactura/*[1]")
        if issuer != nif:
            raise ValueError(f"a record of {issuer} cannot be sent for obligado {nif}")
        etree.SubElement(request, f"{{{NS_LR}}}RegistroFactura").append(element)
    validate(request, "SuministroLR.xsd")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
