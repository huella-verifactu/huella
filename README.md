# huella

[![CI](https://github.com/huella-verifactu/huella/actions/workflows/ci.yml/badge.svg)](https://github.com/huella-verifactu/huella/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/huella)](https://pypi.org/project/huella/)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)

Open-source Python core for **Verifactu**, Spain's tamper-evident invoice record system
(RD 1007/2023, Orden HAC/1177/2024), in **VERI\*FACTU mode**:

- **Models** that reject what the AEAT would reject (NIF checksums, invoice number characters,
  dates, VAT rates, totals, recipients, corrective invoices, correction flags).
- The **huella**: the SHA-256 hash that chains every billing record to the previous one, tested
  against the AEAT's official vectors.
- **XML** for altas, anulaciones and the SOAP request, **validated against the official XSD**
  before it leaves the library.
- The **QR code** (URL, PNG, SVG) as the AEAT specifies it.
- A **client** for the AEAT web service (mutual TLS) and a parser for its answers.

> **Status: alpha (0.x).** The API may change in any minor release. Scope in v1: Spanish VAT at
> 21, 10 and 4 %, regime 01, invoice types F1, F2, R1, R4, R5 (corrective *por diferencias*).

## Install

```sh
pip install huella            # library
pip install "huella[cli]"     # plus .p12/.pfx support for the development CLI
```

## Quick start

```python
from datetime import UTC, datetime

from huella import InvoiceAlta, SistemaInformatico, hash_record, timestamp_madrid
from huella import qr, xml
from huella.models import Environment

alta = InvoiceAlta.model_validate(
    {
        "issuer_nif": "B12345674",
        "issuer_name": "TIENDA EJEMPLO SL",
        "number": "2026-000123",
        "issue_date": "2026-01-20",
        "type": "F2",
        "description": "Venta online - pedido 1234",
        "tax_lines": [{"rate": "21.00", "base": "82.64", "tax": "17.36"}],
        "total": "100.00",
    }
)  # raises pydantic.ValidationError with field paths on any rule
sif = SistemaInformatico(
    producer_name="PRODUCTOR DE EJEMPLO",
    producer_nif="X1234567L",
    version="0.1.0",
    installation_number="HU-0001",
)

ts = timestamp_madrid(datetime.now(UTC))  # "2026-01-20T10:15:03+01:00"
huella = hash_record(alta, previous=None, ts=ts)  # first record of the chain
record = xml.registro_alta(alta, previous=None, ts=ts, huella=huella, sif=sif)
request = xml.envelope(obligado=("TIENDA EJEMPLO SL", "B12345674"), registros=[record])
url = qr.url(alta, Environment.TEST)  # .../ValidarQR?nif=B12345674&...
```

Sending (needs the taxpayer's qualified certificate):

```python
from huella.aeat import AeatClient, client_ssl_context

context = client_ssl_context("cert.pem", "key.pem")
with AeatClient(env=Environment.TEST, ssl_context=context) as aeat:
    result = aeat.send(request)
print(result.status, result.wait_seconds, [r.status for r in result.records])
```

`result.wait_seconds` is the AEAT's `TiempoEsperaEnvio`: wait that long, or until 1,000 records
have queued, before the next request.

## Development CLI

A batch file lists the records to chain (see [`examples/batch.json`](examples/batch.json)):

```sh
huella hash examples/batch.json                  # chained huellas, as JSON
huella xml  examples/batch.json --out req.xml    # the SOAP request, XSD-validated
huella send examples/batch.json --cert my.p12 --password-env P12_PASSWORD --save out/
```

`send` targets the AEAT **pre-production** environment by default. Production needs
`--env production --yes-production`, because production records are real tax records and cannot
be deleted. The output includes `next_previous`: put it in the next batch to continue the chain.

## Hash traps

The huella is a SHA-256 over text, so values that look equal but are spelled differently produce a
different hash. Each row is a test in `tests/test_hash.py`.

| Trap | Wrong | Right |
|---|---|---|
| Amount decimals | `123.4` | `123.40` (always 2 decimals, the same string in the hash and the XML) |
| Decimal separator | `123,45` | `123.45` |
| Time zone | `2024-01-01T18:20:30Z` or `+00:00` | `2024-01-01T19:20:30+01:00` (Madrid time, explicit offset) |
| Date format | `2024-01-01` | `01-01-2024` |
| URL encoding | `12345678%2FG33` | `12345678/G33` (encoding belongs only in the QR URL) |
| Previous huella case | lowercase hex | uppercase hex |
| Empty previous huella | field left out | `Huella=` present with an empty value |

## Security notes

- Certificates are a legal identity. Keep `.p12`/`.pfx` files and passwords out of repositories
  and logs. The CLI reads passwords from an environment variable or a prompt, never from an
  argument, and writes the key to disk only encrypted, for the moment the TLS context loads.
- XML from outside (AEAT answers, stored records) is parsed with DTDs, entities and network
  access disabled.
- Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Development

```sh
uv sync
uv run pytest --cov
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The official AEAT schemas are in `src/huella/specs/v1_0/` (sources and dates in `SOURCES.md`).
The reference PDFs are not committed; `uv run python scripts/fetch_specs.py` downloads them and
reports any file the AEAT has changed since. A workflow runs that check every morning and opens an
issue on drift. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Disclaimer

This project is **not affiliated with, endorsed by or supported by the Agencia Tributaria
(AEAT)**. Using this library does not by itself make any software compliant with Verifactu: the
producer of a billing system remains responsible for the whole system, including its
*declaración responsable*. The software is provided "as is", without warranty of any kind (see the
licence).

## Licence

[Apache-2.0](LICENSE). The AEAT files in `src/huella/specs/` are reused under the AEAT's
conditions; see [NOTICE](NOTICE).
