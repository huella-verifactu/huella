"""AEAT client and response parsing (SPEC 3.8). No network: httpx.MockTransport only."""

import datetime as dt
import ssl
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from lxml import etree

from huella.aeat import (
    DEFAULT_WAIT_SECONDS,
    ENDPOINTS,
    AeatClient,
    RecordStatus,
    SubmissionStatus,
    client_ssl_context,
    parse_response,
)
from huella.errors import AeatFault, CertificateError, TransportError
from huella.models import Environment
from huella.xml import load_schema

FIXTURES = Path(__file__).parent / "fixtures" / "aeat_responses"
NS_R = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/"
    "tike/cont/ws/RespuestaSuministro.xsd"
)
ENVELOPE = b"<soapenv:Envelope/>"  # the client sends bytes as given; content is not inspected


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- The fixtures themselves follow the official response schema -----------------------------


@pytest.mark.parametrize("name", ["correcto.xml", "parcialmente_correcto.xml", "duplicado.xml"])
def test_fixture_is_valid_against_the_response_xsd(name: str) -> None:
    root = etree.fromstring(fixture(name))
    response = root.find(f".//{{{NS_R}}}RespuestaRegFactuSistemaFacturacion")
    assert response is not None
    schema = load_schema("RespuestaSuministro.xsd")
    assert schema.validate(response), schema.error_log


# --- parse_response ------------------------------------------------------------------------------


def test_all_accepted() -> None:
    result = parse_response(fixture("correcto.xml"))
    assert result.status is SubmissionStatus.CORRECT
    assert result.csv == "A-TESTCSV0000001"
    assert result.wait_seconds == 60
    madrid_winter = dt.timezone(dt.timedelta(hours=1))
    assert result.presented_at == dt.datetime(2026, 1, 20, 10, 15, 5, tzinfo=madrid_winter)
    assert [(r.number, r.operation, r.status) for r in result.records] == [
        ("2026-000123", "Alta", RecordStatus.ACCEPTED),
        ("2026-000100", "Anulacion", RecordStatus.ACCEPTED),
    ]
    first = result.records[0]
    assert (first.issuer_nif, first.issue_date) == ("B12345674", dt.date(2026, 1, 20))
    assert first.error_code is None
    assert first.duplicate is None


def test_partially_accepted() -> None:
    result = parse_response(fixture("parcialmente_correcto.xml"))
    assert result.status is SubmissionStatus.PARTIALLY_CORRECT
    assert result.wait_seconds == 120
    accepted, with_errors, rejected = result.records
    assert accepted.status is RecordStatus.ACCEPTED
    assert (with_errors.status, with_errors.error_code) == (RecordStatus.ACCEPTED_WITH_ERRORS, 2004)
    assert with_errors.error_message is not None
    assert with_errors.error_message.startswith("El valor del campo FechaHoraHusoGenRegistro")
    assert (rejected.status, rejected.error_code) == (RecordStatus.REJECTED, 1104)


def test_duplicate() -> None:
    result = parse_response(fixture("duplicado.xml"))
    assert result.status is SubmissionStatus.INCORRECT
    assert result.csv is None
    record = result.records[0]
    assert (record.status, record.error_code) == (RecordStatus.REJECTED, 3000)
    assert record.duplicate is not None
    assert record.duplicate.state == "Correcta"
    assert record.duplicate.request_id == "20260120101505000001"


def test_missing_wait_time_defaults_to_60_seconds() -> None:
    xml = fixture("correcto.xml").replace(
        b"<tikR:TiempoEsperaEnvio>60</tikR:TiempoEsperaEnvio>", b""
    )
    assert parse_response(xml).wait_seconds == DEFAULT_WAIT_SECONDS == 60


def test_client_fault_is_not_retryable() -> None:
    with pytest.raises(AeatFault) as exc:
        parse_response(fixture("fault_client.xml"))
    assert exc.value.code == 4104
    assert not exc.value.retryable
    assert "no está identificado" in exc.value.message


def test_server_fault_is_retryable() -> None:
    with pytest.raises(AeatFault) as exc:
        parse_response(fixture("fault_server.xml"))
    assert exc.value.code is None
    assert exc.value.retryable


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            (FIXTURES / "correcto.xml")
            .read_bytes()
            .replace(b"<tikR:EstadoEnvio>Correcto</tikR:EstadoEnvio>", b""),
            id="status-missing",
        ),
        pytest.param(
            (FIXTURES / "correcto.xml")
            .read_bytes()
            .replace(b">Correcto</tikR:EstadoEnvio>", b">Raro</tikR:EstadoEnvio>"),
            id="status-unknown",
        ),
        pytest.param(b"", id="empty"),
        pytest.param(b"<html><body>Service unavailable</body></html>", id="html"),
        pytest.param(b"not xml at all", id="garbage"),
        pytest.param(
            b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', id="doctype"
        ),
    ],
)
def test_unusable_response_is_a_transport_error(body: bytes) -> None:
    with pytest.raises(TransportError):
        parse_response(body)


# --- AeatClient ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "seal", "host"),
    [
        (Environment.TEST, False, "prewww1.aeat.es"),
        (Environment.TEST, True, "prewww10.aeat.es"),
        (Environment.PRODUCTION, False, "www1.agenciatributaria.gob.es"),
        (Environment.PRODUCTION, True, "www10.agenciatributaria.gob.es"),
    ],
)
def test_endpoints_match_the_wsdl(env: Environment, seal: bool, host: str) -> None:
    assert ENDPOINTS[env, seal] == (
        f"https://{host}/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
    )


def client(handler: Callable[[httpx.Request], httpx.Response]) -> AeatClient:
    return AeatClient(
        env=Environment.TEST,
        ssl_context=ssl.create_default_context(),
        transport=httpx.MockTransport(handler),
    )


def test_send_posts_the_envelope_and_parses_the_answer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=fixture("correcto.xml"))

    with client(handler) as aeat:
        result = aeat.send(ENVELOPE)
    assert result.status is SubmissionStatus.CORRECT
    assert result.raw == fixture("correcto.xml")
    request = seen[0]
    assert str(request.url) == ENDPOINTS[Environment.TEST, False]
    assert request.method == "POST"
    assert request.content == ENVELOPE
    assert request.headers["content-type"] == "text/xml; charset=utf-8"


def test_soap_fault_with_http_500_raises_the_fault() -> None:
    fault = fixture("fault_client.xml")
    with (
        client(lambda _: httpx.Response(500, content=fault)) as aeat,
        pytest.raises(AeatFault) as exc,
    ):
        aeat.send(ENVELOPE)
    assert exc.value.code == 4104


@pytest.mark.parametrize("status", [502, 503, 504])
def test_gateway_errors_are_transport_errors(status: int) -> None:
    bad_gateway = httpx.Response(status, content=b"Bad gateway")
    with client(lambda _: bad_gateway) as aeat, pytest.raises(TransportError, match=str(status)):
        aeat.send(ENVELOPE)


@pytest.mark.parametrize("status", [401, 403])
def test_refused_client_certificate(status: int) -> None:
    with client(lambda _: httpx.Response(status)) as aeat, pytest.raises(CertificateError):
        aeat.send(ENVELOPE)


def test_timeout_is_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with client(handler) as aeat, pytest.raises(TransportError, match="timed out"):
        aeat.send(ENVELOPE)


@pytest.mark.parametrize(
    "message",
    [
        "[SSL: SSLV3_ALERT_BAD_CERTIFICATE] sslv3 alert bad certificate",
        "[SSL: TLSV1_ALERT_UNKNOWN_CA] tlsv1 alert unknown ca",
        "[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] tlsv13 alert certificate required",
        "[SSL: SSLV3_ALERT_CERTIFICATE_EXPIRED] sslv3 alert certificate expired",
        "[SSL: SSLV3_ALERT_CERTIFICATE_REVOKED] sslv3 alert certificate revoked",
    ],
)
def test_the_aeat_refusing_our_certificate_is_a_certificate_error(message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message, request=request)

    with client(handler) as aeat, pytest.raises(CertificateError):
        aeat.send(ENVELOPE)


@pytest.mark.parametrize(
    "message",
    [
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer",
        "[SSL: WRONG_VERSION_NUMBER] wrong version number",
        "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure",
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
    ],
)
def test_other_tls_failures_are_not_the_taxpayers_fault(message: str) -> None:
    # Above all CERTIFICATE_VERIFY_FAILED: *we* could not verify the AEAT (a broken trust store).
    # As a CertificateError it would pause every customer at once.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message, request=request)

    with client(handler) as aeat, pytest.raises(TransportError):
        aeat.send(ENVELOPE)


def test_plain_connection_failure_is_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with client(handler) as aeat, pytest.raises(TransportError):
        aeat.send(ENVELOPE)


# --- Client certificate loading ------------------------------------------------------------------


def _self_signed(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "huella test client")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / "client.pem", folder / "client.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


def test_client_ssl_context_loads_pem_files(tmp_path: Path) -> None:
    cert_file, key_file = _self_signed(tmp_path)
    context = client_ssl_context(cert_file, key_file)
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname


def test_client_ssl_context_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CertificateError, match="certificate"):
        client_ssl_context(tmp_path / "missing.pem")


def test_client_ssl_context_reports_a_mismatched_key(tmp_path: Path) -> None:
    cert_file, _ = _self_signed(tmp_path / "a")
    _, other_key = _self_signed(tmp_path / "b")
    with pytest.raises(CertificateError):
        client_ssl_context(cert_file, other_key)
