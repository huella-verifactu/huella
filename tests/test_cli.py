"""Development CLI (SPEC 4.4). No network: the AEAT is an httpx.MockTransport."""

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from huella.cli import main
from huella.cli import run as run_script
from huella.hash import hash_record
from huella.models import ChainLink, InvoiceAlta, InvoiceAnulacion
from huella.xml import NS_LR

EXAMPLE = Path(__file__).parent.parent / "examples" / "batch.json"
RESPONSES = Path(__file__).parent / "fixtures" / "aeat_responses"


def run(capsys: pytest.CaptureFixture[str], *argv: str, **kwargs: Any) -> tuple[int, str, str]:
    code = main(list(argv), **kwargs)
    out, err = capsys.readouterr()
    return code, out, err


def answering(name: str) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda _: httpx.Response(200, content=(RESPONSES / name).read_bytes())
    )


def write_batch(tmp_path: Path, **changes: Any) -> Path:
    batch = json.loads(EXAMPLE.read_text(encoding="utf-8")) | changes
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    return path


def certificate(tmp_path: Path) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "huella cli test")])
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
    return cert, key


# --- hash --------------------------------------------------------------------------------------


def test_hash_chains_every_record_of_the_example(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "hash", str(EXAMPLE))
    assert code == 0
    result = json.loads(out)
    batch = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    previous = None
    for entry, printed in zip(batch["records"], result["records"], strict=True):
        model = InvoiceAlta if entry["kind"] == "alta" else InvoiceAnulacion
        record = model.model_validate(entry["invoice"])
        expected = hash_record(record, previous=previous, ts=entry["ts"])
        assert printed == {
            "kind": entry["kind"],
            "number": record.number,
            "ts": entry["ts"],
            "huella": expected,
        }
        previous = ChainLink(number=record.number, issue_date=record.issue_date, huella=expected)
    assert previous is not None
    assert result["next_previous"] == {
        "number": previous.number,
        "issue_date": previous.issue_date.isoformat(),
        "huella": previous.huella,
    }


def test_hash_continues_from_the_given_previous_record(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    previous = {"number": "2026-000122", "issue_date": "2026-01-19", "huella": "A" * 64}
    _, out, _ = run(capsys, "hash", str(write_batch(tmp_path, previous=previous)))
    first = json.loads(out)["records"][0]
    alta = InvoiceAlta.model_validate(json.loads(EXAMPLE.read_text())["records"][0]["invoice"])
    link = ChainLink.model_validate(previous)
    assert first["huella"] == hash_record(alta, previous=link, ts=first["ts"])


def test_hash_without_ts_uses_the_current_madrid_time(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    batch = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    del batch["records"][0]["ts"]
    _, out, _ = run(capsys, "hash", str(write_batch(tmp_path, records=batch["records"][:1])))
    ts = json.loads(out)["records"][0]["ts"]
    assert ts[-6:] in {"+01:00", "+02:00"}


def test_invalid_batch_reports_the_field(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    batch = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    batch["records"][0]["invoice"]["issuer_nif"] = "B12345678"
    code, out, err = run(capsys, "hash", str(write_batch(tmp_path, records=batch["records"])))
    assert code == 1
    assert out == ""
    assert "issuer_nif" in err


def test_missing_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, _, err = run(capsys, "hash", str(tmp_path / "nope.json"))
    assert code == 1
    assert "error:" in err


# --- xml ---------------------------------------------------------------------------------------


def test_xml_prints_a_valid_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "xml", str(EXAMPLE))
    assert code == 0
    root = etree.fromstring(out.encode())
    assert len(root.findall(f".//{{{NS_LR}}}RegistroFactura")) == 3


def test_xml_writes_to_a_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    target = tmp_path / "request.xml"
    code, out, _ = run(capsys, "xml", str(EXAMPLE), "--out", str(target))
    assert (code, out) == (0, "")
    assert target.read_bytes().startswith(b"<?xml")


# --- send --------------------------------------------------------------------------------------


def pem_files(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = certificate(tmp_path)
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


def test_send_with_pem_files(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    cert_file, key_file = pem_files(tmp_path)
    saved = tmp_path / "saved"
    code, out, _ = run(
        capsys,
        "send", str(EXAMPLE), "--env", "test", "--cert", str(cert_file), "--key", str(key_file),
        "--save", str(saved),
        transport=answering("correcto.xml"),
    )  # fmt: skip
    assert code == 0
    result = json.loads(out)
    assert (result["status"], result["csv"], result["wait_seconds"]) == (
        "Correcto",
        "A-TESTCSV0000001",
        60,
    )
    assert result["records"][0] == {
        "number": "2026-000123",
        "operation": "Alta",
        "status": "Correcto",
        "error_code": None,
        "error_message": None,
    }
    assert "next_previous" in result
    assert (saved / "request.xml").read_bytes().startswith(b"<?xml")
    assert (saved / "response.xml").read_bytes() == (RESPONSES / "correcto.xml").read_bytes()


def test_send_with_a_p12_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cert, key = certificate(tmp_path)
    p12 = tmp_path / "cert.p12"
    p12.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"test", key, cert, None, serialization.BestAvailableEncryption(b"s3cret")
        )
    )
    monkeypatch.setenv("HUELLA_TEST_P12_PASSWORD", "s3cret")
    code, out, _ = run(
        capsys,
        "send", str(EXAMPLE), "--cert", str(p12), "--password-env", "HUELLA_TEST_P12_PASSWORD",
        transport=answering("parcialmente_correcto.xml"),
    )  # fmt: skip
    assert code == 2  # not everything was accepted
    statuses = [r["status"] for r in json.loads(out)["records"]]
    assert statuses == ["Correcto", "AceptadoConErrores", "Incorrecto"]


def test_send_with_a_wrong_p12_password(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cert, key = certificate(tmp_path)
    p12 = tmp_path / "cert.p12"
    encryption = serialization.BestAvailableEncryption(b"right")
    p12.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, encryption))
    monkeypatch.setenv("HUELLA_TEST_P12_PASSWORD", "wrong")
    code, _, err = run(
        capsys,
        "send", str(EXAMPLE), "--cert", str(p12), "--password-env", "HUELLA_TEST_P12_PASSWORD",
        transport=answering("correcto.xml"),
    )  # fmt: skip
    assert code == 1
    assert "certificate" in err


def test_send_to_production_needs_explicit_confirmation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cert_file, key_file = pem_files(tmp_path)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=(RESPONSES / "correcto.xml").read_bytes())

    code, _, err = run(
        capsys,
        "send", str(EXAMPLE), "--env", "production", "--cert", str(cert_file),
        "--key", str(key_file),
        transport=httpx.MockTransport(handler),
    )  # fmt: skip
    assert code == 1
    assert "--yes-production" in err
    assert calls == []


def test_send_reports_a_soap_fault(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    cert_file, key_file = pem_files(tmp_path)
    fault = (RESPONSES / "fault_client.xml").read_bytes()
    code, out, err = run(
        capsys,
        "send", str(EXAMPLE), "--cert", str(cert_file), "--key", str(key_file),
        transport=httpx.MockTransport(lambda _: httpx.Response(500, content=fault)),
    )  # fmt: skip
    assert (code, out) == (1, "")
    assert "4104" in err


def test_no_command_shows_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "usage" in capsys.readouterr().err


def p12_file(tmp_path: Path, password: bytes, *, with_key: bool = True) -> Path:
    cert, key = certificate(tmp_path)
    path = tmp_path / "cert.pfx"
    encryption = serialization.BestAvailableEncryption(password)
    blob = pkcs12.serialize_key_and_certificates(
        b"t", key if with_key else None, cert, None, encryption
    )
    path.write_bytes(blob)
    return path


def test_send_prompts_for_the_password(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "pw")
    p12 = p12_file(tmp_path, b"pw")
    code, _, _ = run(
        capsys, "send", str(EXAMPLE), "--cert", str(p12), transport=answering("correcto.xml")
    )
    assert code == 0


def test_send_with_an_unset_password_variable(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HUELLA_UNSET_VAR", raising=False)
    p12 = p12_file(tmp_path, b"pw")
    code, _, err = run(
        capsys, "send", str(EXAMPLE), "--cert", str(p12), "--password-env", "HUELLA_UNSET_VAR"
    )
    assert code == 1
    assert "HUELLA_UNSET_VAR" in err


def test_p12_without_a_private_key(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUELLA_TEST_P12_PASSWORD", "pw")
    p12 = p12_file(tmp_path, b"pw", with_key=False)
    code, _, err = run(
        capsys,
        "send",
        str(EXAMPLE),
        "--cert",
        str(p12),
        "--password-env",
        "HUELLA_TEST_P12_PASSWORD",
    )
    assert code == 1
    assert "private key" in err


def test_p12_needs_the_cli_extra(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUELLA_TEST_P12_PASSWORD", "pw")
    p12 = p12_file(tmp_path, b"pw")
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.serialization", None)
    code, _, err = run(
        capsys,
        "send",
        str(EXAMPLE),
        "--cert",
        str(p12),
        "--password-env",
        "HUELLA_TEST_P12_PASSWORD",
    )
    assert code == 1
    assert "huella[cli]" in err


def test_console_script_exits_with_the_command_status(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["huella", "hash", str(EXAMPLE)])
    with pytest.raises(SystemExit) as exc:
        run_script()
    assert exc.value.code == 0
    assert "next_previous" in capsys.readouterr().out
