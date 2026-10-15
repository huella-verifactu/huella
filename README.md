# huella

[![CI](https://github.com/huella-verifactu/huella/actions/workflows/ci.yml/badge.svg)](https://github.com/huella-verifactu/huella/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/huella)](https://pypi.org/project/huella/)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)

Open-source Python core for **Verifactu**, Spain's tamper-evident invoice record system
(RD 1007/2023, Orden HAC/1177/2024): exact field formatting, the *huella* (the SHA-256 hash that
chains every billing record to the previous one), and, in the coming releases, record models, XML
with XSD validation, QR codes and the AEAT web service client.

> **Status: pre-alpha (0.0.x).** Formatting and hashing are implemented and tested against the
> AEAT's official test vectors. Models, XML, QR and the AEAT client arrive in 0.1.0. The API may
> change in any 0.x release.

## Quick start

```sh
pip install huella
```

```python
from datetime import UTC, datetime
from decimal import Decimal

from huella import format_amount, huella_alta, round_amount, timestamp_madrid

h = huella_alta(
    nif="89890001K",
    num="12345678/G33",
    fecha="01-01-2024",
    tipo="F1",
    cuota=format_amount(round_amount(Decimal("12.345"))),  # "12.35"
    importe=format_amount(Decimal("123.45")),
    previa=None,  # first record of the chain
    ts=timestamp_madrid(
        datetime(2024, 1, 1, 18, 20, 30, tzinfo=UTC)
    ),  # "2024-01-01T19:20:30+01:00"
)
assert h == "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60"
```

## Hash traps

The huella is a SHA-256 over text, so values that look equal but are spelled differently produce a
different hash. Each row below is a test in `tests/test_hash.py`.

| Trap | Wrong | Right |
|---|---|---|
| Amount decimals | `123.4` | `123.40` (always 2 decimals, the same string in the hash and the XML) |
| Decimal separator | `123,45` | `123.45` |
| Time zone | `2024-01-01T18:20:30Z` or `+00:00` | `2024-01-01T19:20:30+01:00` (Madrid time, explicit offset) |
| Date format | `2024-01-01` | `01-01-2024` |
| URL encoding | `12345678%2FG33` | `12345678/G33` (encoding belongs only in the QR URL) |
| Previous huella case | lowercase hex | uppercase hex |
| Empty previous huella | field left out | `Huella=` present with an empty value |

## Development

```sh
uv sync
uv run pytest --cov
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The official AEAT schemas are in `src/huella/specs/v1_0/` (sources and dates in `SOURCES.md`).
The reference PDFs are not committed; `uv run python scripts/fetch_specs.py` downloads them. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Disclaimer

This project is **not affiliated with, endorsed by or supported by the Agencia Tributaria
(AEAT)**. Using this library does not by itself make any software compliant with Verifactu: the
producer of a billing system remains responsible for the whole system, including its
*declaración responsable*. The software is provided "as is", without warranty of any kind (see the
licence).

## Licence

[Apache-2.0](LICENSE). The AEAT files in `src/huella/specs/` are reused under the AEAT's
conditions; see [NOTICE](NOTICE).
