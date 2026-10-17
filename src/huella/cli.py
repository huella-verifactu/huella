"""Development CLI: hash, build and send records to the AEAT (SPEC 4.4).

    huella hash  batch.json
    huella xml   batch.json [--out request.xml]
    huella send  batch.json --cert cert.p12 [--password-env VAR] [--env test] [--save DIR]
    huella consulta --cert cert.p12 --nif B12345674 --name "TIENDA SL" --year 2026 --month 1
        [--number 2026-000123] [--date 2026-01-20] [--env test]

``consulta`` asks which records the AEAT holds (registers nothing, so it is also the way to
check a production connection without a real invoice).

A batch file holds the obligado, the SistemaInformatico block, the previous chain link (or null)
and the records, chained in order; see ``examples/batch.json``. Output is JSON on stdout. It
includes ``next_previous``: put it in the next batch file to continue the chain.

For development and pre-production tests only: Huella Cloud keeps the chain in a database.
"""

import argparse
import getpass
import json
import os
import secrets
import ssl
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn

import httpx
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from huella.aeat import DEFAULT_TIMEOUT_S, AeatClient, SubmissionStatus, client_ssl_context
from huella.consulta import HeldRecord, PageKey, consulta_envelope
from huella.errors import CertificateError, HuellaError
from huella.format import timestamp_madrid
from huella.hash import hash_record
from huella.models import (
    ChainLink,
    Environment,
    InvoiceAlta,
    InvoiceAnulacion,
    SistemaInformatico,
)
from huella.xml import MAX_RECORDS, envelope, registro_alta, registro_anulacion

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_ALL_ACCEPTED = 2


class UsageError(Exception):
    """A mistake in how the CLI was called."""


# --- Batch file --------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Obligado(_Strict):
    name: str
    nif: str


class AltaEntry(_Strict):
    kind: Literal["alta"]
    ts: str | None = None  # default: now, Madrid time
    invoice: InvoiceAlta


class AnulacionEntry(_Strict):
    kind: Literal["anulacion"]
    ts: str | None = None
    invoice: InvoiceAnulacion


Entry = Annotated[AltaEntry | AnulacionEntry, Field(discriminator="kind")]


class Batch(_Strict):
    obligado: Obligado
    sif: SistemaInformatico
    previous: ChainLink | None = None
    records: Annotated[list[Entry], Field(min_length=1, max_length=MAX_RECORDS)]


@dataclass(frozen=True)
class Built:
    kind: str
    number: str
    ts: str
    huella: str
    element: etree._Element


def _load(path: Path) -> Batch:
    return Batch.model_validate_json(path.read_bytes())


def _build(batch: Batch) -> tuple[list[Built], ChainLink | None]:
    """Hash and build every record, each chained to the one before it."""
    previous = batch.previous
    built: list[Built] = []
    for entry in batch.records:
        ts = entry.ts or timestamp_madrid(datetime.now(UTC))
        huella = hash_record(entry.invoice, previous=previous, ts=ts)
        if isinstance(entry, AltaEntry):
            element = registro_alta(
                entry.invoice, previous=previous, ts=ts, huella=huella, sif=batch.sif
            )
        else:
            element = registro_anulacion(
                entry.invoice, previous=previous, ts=ts, huella=huella, sif=batch.sif
            )
        built.append(Built(entry.kind, entry.invoice.number, ts, huella, element))
        previous = ChainLink(
            number=entry.invoice.number, issue_date=entry.invoice.issue_date, huella=huella
        )
    return built, previous


def _envelope(batch: Batch, built: list[Built]) -> bytes:
    return envelope(
        obligado=(batch.obligado.name, batch.obligado.nif),
        registros=[record.element for record in built],
    )


def _link_json(link: ChainLink | None) -> dict[str, str] | None:
    return None if link is None else link.model_dump(mode="json")


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# --- Certificates ------------------------------------------------------------------------------


def _password(args: argparse.Namespace) -> bytes:
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value is None:
            raise UsageError(f"environment variable {args.password_env} is not set")
        return value.encode()
    return getpass.getpass("Certificate password: ").encode()


def _context_from_p12(data: bytes, password: bytes) -> ssl.SSLContext:
    try:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: PLC0415
    except ImportError as exc:
        raise UsageError("reading .p12/.pfx files needs: pip install 'huella[cli]'") from exc
    try:
        key, cert, chain = pkcs12.load_key_and_certificates(data, password)
    except ValueError as exc:
        raise CertificateError(f"cannot open the certificate (wrong password?): {exc}") from exc
    if key is None or cert is None:
        raise CertificateError("the certificate file has no private key or no certificate")
    # Python's ssl loads keys only from files, so write an encrypted copy that lives only
    # while the context loads; the plaintext key never touches the disk.
    transient = secrets.token_bytes(32)
    pem = serialization.Encoding.PEM
    encrypted_key = key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(transient)
    )
    certificates = b"".join(c.public_bytes(pem) for c in [cert, *chain])
    with tempfile.TemporaryDirectory() as folder:
        cert_file, key_file = Path(folder) / "cert.pem", Path(folder) / "key.pem"
        cert_file.write_bytes(certificates)
        key_file.write_bytes(encrypted_key)
        return client_ssl_context(cert_file, key_file, transient)


def _ssl_context(args: argparse.Namespace) -> ssl.SSLContext:
    cert: Path = args.cert
    if cert.suffix.lower() in {".p12", ".pfx"}:
        return _context_from_p12(cert.read_bytes(), _password(args))
    return client_ssl_context(cert, args.key)


# --- Commands ----------------------------------------------------------------------------------


def _cmd_hash(args: argparse.Namespace) -> int:
    built, last = _build(_load(args.file))
    records = [{"kind": b.kind, "number": b.number, "ts": b.ts, "huella": b.huella} for b in built]
    _print_json({"records": records, "next_previous": _link_json(last)})
    return EXIT_OK


def _cmd_xml(args: argparse.Namespace) -> int:
    batch = _load(args.file)
    built, _ = _build(batch)
    xml = _envelope(batch, built)
    if args.out is None:
        print(xml.decode())
    else:
        args.out.write_bytes(xml)
    return EXIT_OK


def _cmd_send(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    env = Environment(args.env)
    if env is Environment.PRODUCTION and not args.yes_production:
        raise UsageError(
            "production records are real tax records and cannot be deleted; "
            "add --yes-production if that is what you want"
        )
    batch = _load(args.file)
    built, last = _build(batch)
    request = _envelope(batch, built)
    if args.save is not None:
        args.save.mkdir(parents=True, exist_ok=True)
        (args.save / "request.xml").write_bytes(request)
    with AeatClient(
        env=env,
        ssl_context=_ssl_context(args),
        seal=args.seal,
        timeout=args.timeout,
        transport=transport,
    ) as client:
        result = client.send(request)
    if args.save is not None:
        (args.save / "response.xml").write_bytes(result.raw)
    _print_json(
        {
            "status": result.status.value,
            "csv": result.csv,
            "wait_seconds": result.wait_seconds,
            "records": [
                {
                    "number": r.number,
                    "operation": r.operation,
                    "status": r.status.value,
                    "error_code": r.error_code,
                    "error_message": r.error_message,
                }
                for r in result.records
            ],
            "next_previous": _link_json(last),
        }
    )
    return EXIT_OK if result.status is SubmissionStatus.CORRECT else EXIT_NOT_ALL_ACCEPTED


MAX_CONSULTA_PAGES = 50


def _held_json(record: HeldRecord) -> dict[str, Any]:
    return {
        "issuer_nif": record.issuer_nif,
        "number": record.number,
        "issue_date": record.issue_date.isoformat(),
        "state": record.state.value,
        "huella": record.huella,
        "generated_at": record.generated_at,
        "type": record.invoice_type,
        "total": record.total,
        "tax_total": record.tax_total,
        "subsanacion": record.subsanacion,
        "last_modified": record.last_modified,
        "error_code": record.error_code,
        "error_message": record.error_message,
    }


def _cmd_consulta(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    held: list[HeldRecord] = []
    page: PageKey | None = None
    with AeatClient(
        env=Environment(args.env),
        ssl_context=_ssl_context(args),
        seal=args.seal,
        timeout=args.timeout,
        transport=transport,
    ) as client:
        for _ in range(MAX_CONSULTA_PAGES):
            request = consulta_envelope(
                obligado=(args.name, args.nif),
                year=args.year,
                month=args.month,
                number=args.number,
                issue_date=args.date,
                page=page,
            )
            result = client.consulta(request)
            held.extend(result.records)
            if result.next_page is not None and result.next_page == page:
                raise UsageError("the AEAT returned the same page twice; stopping")
            page = result.next_page
            if page is None:
                break
    _print_json({"records": [_held_json(r) for r in held], "complete": page is None})
    if page is not None:
        print(
            f"warning: stopped after {MAX_CONSULTA_PAGES} pages; narrow the query "
            "(--number, --date) to see the rest",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return EXIT_OK


# --- Entry point -------------------------------------------------------------------------------


def _connection_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--env", choices=["test", "production"], default="test")
    command.add_argument("--cert", type=Path, required=True, help=".p12/.pfx or PEM")
    command.add_argument("--key", type=Path, help="PEM private key, if not in --cert")
    command.add_argument("--password-env", help="env var holding the .p12 password")
    command.add_argument("--seal", action="store_true", help="seal certificate endpoint")
    command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="huella", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("hash", "print the chained huella of every record"),
        ("xml", "print the SOAP request, validated against the AEAT XSD"),
        ("send", "send the records to the AEAT and print its answer"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("file", type=Path, help="batch JSON file")
        if name == "xml":
            command.add_argument("--out", type=Path, help="write to this file instead of stdout")
        if name == "send":
            _connection_options(command)
            command.add_argument("--save", type=Path, help="folder for request/response XML")
            command.add_argument("--yes-production", action="store_true")
    consulta = commands.add_parser("consulta", help="list the records the AEAT holds")
    _connection_options(consulta)
    consulta.add_argument("--nif", required=True, help="the obligado's NIF")
    consulta.add_argument("--name", required=True, help="the obligado's legal name")
    consulta.add_argument("--year", type=int, required=True)
    consulta.add_argument("--month", type=int, required=True, help="1 to 12")
    consulta.add_argument("--number", help="only this invoice number")
    consulta.add_argument("--date", type=date.fromisoformat, help="only this issue date")
    return parser


def _describe(exc: ValidationError) -> str:
    lines = [f"  {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return "invalid batch file:\n" + "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "hash":
            return _cmd_hash(args)
        if args.command == "xml":
            return _cmd_xml(args)
        if args.command == "consulta":
            return _cmd_consulta(args, transport)
        return _cmd_send(args, transport)
    except ValidationError as exc:
        print(f"error: {_describe(exc)}", file=sys.stderr)
    except (UsageError, HuellaError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
    return EXIT_ERROR


def run() -> NoReturn:
    """Console script entry point."""
    sys.exit(main())
