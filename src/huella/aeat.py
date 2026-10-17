"""The AEAT VERI*FACTU web service: endpoints, mTLS client and response parsing (SPEC 3.8).

The only module in huella that does I/O. Failures map to three exceptions the caller can act on:

- :class:`~huella.errors.TransportError`: no usable answer (network, timeout, gateway error,
  unexpected body). Retry later with backoff.
- :class:`~huella.errors.AeatFault`: a SOAP fault refused the whole request. ``retryable`` is
  true for ``env:Server`` faults only.
- :class:`~huella.errors.CertificateError`: the client certificate is unusable or refused.
  Pause the issuer and alert; retrying will not help.

Per-record outcomes (accepted, accepted with errors, rejected, duplicate) are data, not
exceptions: see :class:`SubmissionResult`.
"""

import ssl
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Self

import httpx
from lxml import etree

from huella._soap import fault, parse_xml
from huella.consulta import ConsultaResult, parse_consulta
from huella.errors import CertificateError, TransportError
from huella.models import Environment
from huella.xml import NS_SF, NS_SOAP

_SOAP_PATH = "/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
# (environment, seal certificate) -> endpoint, as in SistemaFacturacion.wsdl
ENDPOINTS: dict[tuple[Environment, bool], str] = {
    (Environment.TEST, False): "https://prewww1.aeat.es" + _SOAP_PATH,
    (Environment.TEST, True): "https://prewww10.aeat.es" + _SOAP_PATH,
    (Environment.PRODUCTION, False): "https://www1.agenciatributaria.gob.es" + _SOAP_PATH,
    (Environment.PRODUCTION, True): "https://www10.agenciatributaria.gob.es" + _SOAP_PATH,
}
NS_R = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/"
    "tike/cont/ws/RespuestaSuministro.xsd"
)
DEFAULT_WAIT_SECONDS = 60  # Orden HAC/1177/2024 art. 16.2: initial value of the wait time
DEFAULT_TIMEOUT_S = 30.0
_NS = {"r": NS_R, "sf": NS_SF}
_HTTP_UNAUTHORIZED = frozenset({401, 403})
_HTTP_WITH_SOAP_BODY = frozenset({200, 500})  # SOAP 1.1 faults travel with HTTP 500
# TLS alerts a server sends about the *client's* certificate. Any other TLS failure (our own
# failure to verify the AEAT's certificate, a middlebox, a protocol error, an ambiguous
# handshake_failure) is not the taxpayer's fault: TransportError, retried, never a pause.
_CLIENT_CERTIFICATE_ALERTS = (
    "BAD_CERTIFICATE",
    "UNKNOWN_CA",
    "CERTIFICATE_REQUIRED",
    "CERTIFICATE_EXPIRED",
    "CERTIFICATE_REVOKED",
    "CERTIFICATE_UNKNOWN",
    "UNSUPPORTED_CERTIFICATE",
)


class SubmissionStatus(StrEnum):
    """``EstadoEnvio``: the outcome of the request as a whole."""

    CORRECT = "Correcto"
    PARTIALLY_CORRECT = "ParcialmenteCorrecto"
    INCORRECT = "Incorrecto"


class RecordStatus(StrEnum):
    """``EstadoRegistro``: the outcome of one record."""

    ACCEPTED = "Correcto"
    ACCEPTED_WITH_ERRORS = "AceptadoConErrores"
    REJECTED = "Incorrecto"


@dataclass(frozen=True)
class Duplicate:
    """``RegistroDuplicado``: the AEAT already holds this record.

    Typical cause: a retry after a lost answer (SPEC 3.8 says how to resolve it).
    """

    request_id: str
    state: str  # Correcta | AceptadaConErrores | Anulada
    error_code: int | None
    error_message: str | None


@dataclass(frozen=True)
class RecordResult:
    issuer_nif: str
    number: str
    issue_date: date
    operation: str  # Alta | Anulacion
    status: RecordStatus
    error_code: int | None
    error_message: str | None
    duplicate: Duplicate | None


@dataclass(frozen=True)
class SubmissionResult:
    status: SubmissionStatus
    wait_seconds: int  # TiempoEsperaEnvio: wait this long before the next request (SPEC 5.6)
    records: tuple[RecordResult, ...]
    csv: str | None  # secure verification code of the submission
    presented_at: datetime | None
    raw: bytes  # the response exactly as received, for storage


# --- Parsing -------------------------------------------------------------------------------------


def _required(element: etree._Element, path: str) -> str:
    text = element.findtext(path, namespaces=_NS)
    if text is None:
        raise TransportError(f"unexpected AEAT answer: {path} missing")
    return text.strip()


def _optional_int(element: etree._Element, path: str) -> int | None:
    text = element.findtext(path, namespaces=_NS)
    return None if text is None else int(text)


def _duplicate(line: etree._Element) -> Duplicate | None:
    block = line.find("r:RegistroDuplicado", _NS)
    if block is None:
        return None
    return Duplicate(
        request_id=_required(block, "sf:IdPeticionRegistroDuplicado"),
        state=_required(block, "sf:EstadoRegistroDuplicado"),
        error_code=_optional_int(block, "sf:CodigoErrorRegistro"),
        error_message=block.findtext("sf:DescripcionErrorRegistro", namespaces=_NS),
    )


def _record(line: etree._Element) -> RecordResult:
    return RecordResult(
        issuer_nif=_required(line, "r:IDFactura/sf:IDEmisorFactura"),
        number=_required(line, "r:IDFactura/sf:NumSerieFactura"),
        issue_date=datetime.strptime(  # noqa: DTZ007 - a calendar date, no time zone
            _required(line, "r:IDFactura/sf:FechaExpedicionFactura"), "%d-%m-%Y"
        ).date(),
        operation=_required(line, "r:Operacion/sf:TipoOperacion"),
        status=RecordStatus(_required(line, "r:EstadoRegistro")),
        error_code=_optional_int(line, "r:CodigoErrorRegistro"),
        error_message=line.findtext("r:DescripcionErrorRegistro", namespaces=_NS),
        duplicate=_duplicate(line),
    )


def parse_response(body: bytes) -> SubmissionResult:
    """Parse an answer to ``RegFactuSistemaFacturacion``. Raises on faults and unusable bodies."""
    root = parse_xml(body)
    soap_fault = root.find(f"{{{NS_SOAP}}}Body/{{{NS_SOAP}}}Fault")
    if soap_fault is not None:
        raise fault(soap_fault)
    response = root.find(f"{{{NS_SOAP}}}Body/{{{NS_R}}}RespuestaRegFactuSistemaFacturacion")
    if response is None:
        raise TransportError("unexpected AEAT answer: no RespuestaRegFactuSistemaFacturacion")
    try:
        wait = _optional_int(response, "r:TiempoEsperaEnvio")
        presented = response.findtext(
            "r:DatosPresentacion/sf:TimestampPresentacion", namespaces=_NS
        )
        return SubmissionResult(
            status=SubmissionStatus(_required(response, "r:EstadoEnvio")),
            wait_seconds=DEFAULT_WAIT_SECONDS if wait is None else wait,
            records=tuple(_record(line) for line in response.iterfind("r:RespuestaLinea", _NS)),
            csv=response.findtext("r:CSV", namespaces=_NS),
            presented_at=None if presented is None else datetime.fromisoformat(presented),
            raw=body,
        )
    except ValueError as exc:
        raise TransportError(f"unexpected AEAT answer: {exc}") from exc


# --- Client --------------------------------------------------------------------------------------


def client_ssl_context(
    cert_file: str | Path, key_file: str | Path | None = None, password: bytes | None = None
) -> ssl.SSLContext:
    """TLS context with the taxpayer's certificate for mutual TLS (PEM files).

    The AEAT server certificate is verified against the system trust store.
    """
    context = ssl.create_default_context()
    try:
        context.load_cert_chain(cert_file, key_file, password)
    except (OSError, ssl.SSLError) as exc:
        raise CertificateError(f"cannot load the client certificate: {exc}") from exc
    return context


def _refuses_client_certificate(message: str) -> bool:
    upper = message.upper()
    return "ALERT" in upper and any(alert in upper for alert in _CLIENT_CERTIFICATE_ALERTS)


class AeatClient:
    """Sends envelopes from :func:`huella.xml.envelope` to the AEAT over mutual TLS."""

    def __init__(
        self,
        *,
        env: Environment,
        ssl_context: ssl.SSLContext,
        seal: bool = False,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = ENDPOINTS[env, seal]
        self._http = httpx.Client(
            verify=ssl_context,
            timeout=timeout,
            transport=transport,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
        )

    def _post(self, envelope: bytes) -> bytes:
        """POST one SOAP request; the body of an answer that carries SOAP, else an exception."""
        try:
            response = self._http.post(self.endpoint, content=envelope)
        except httpx.ConnectError as exc:
            if _refuses_client_certificate(str(exc)):
                raise CertificateError(f"the AEAT refused the client certificate: {exc}") from exc
            raise TransportError(f"cannot reach the AEAT: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"no usable answer from the AEAT: {exc}") from exc
        if response.status_code in _HTTP_UNAUTHORIZED:
            raise CertificateError(
                f"the AEAT refused the client certificate (HTTP {response.status_code})"
            )
        if response.status_code not in _HTTP_WITH_SOAP_BODY:
            raise TransportError(f"HTTP {response.status_code} from the AEAT")
        return response.content

    def send(self, envelope: bytes) -> SubmissionResult:
        """Register records: an envelope from :func:`huella.xml.envelope`."""
        return parse_response(self._post(envelope))

    def consulta(self, envelope: bytes) -> ConsultaResult:
        """Ask which records the AEAT holds: an envelope from
        :func:`huella.consulta.consulta_envelope`. Registers nothing."""
        return parse_consulta(self._post(envelope))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
