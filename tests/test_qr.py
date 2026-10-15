"""QR code tests (AEAT QR spec; SPEC 3.7). The URL fixture is shared with the plugin."""

import json
import re
import struct
import zlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from huella import qr
from huella.models import Environment, InvoiceAlta

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "qr_cases.json").read_text(encoding="utf-8")
)["cases"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_url_matches_shared_fixture(case: dict[str, Any]) -> None:
    url = qr.url_from_fields(
        nif=case["nif"],
        number=case["number"],
        issue_date=date.fromisoformat(case["issue_date"]),
        total=Decimal(case["total"]),
        env=Environment(case["environment"]),
    )
    assert url == case["url"]


def test_url_from_a_validated_invoice() -> None:
    alta = InvoiceAlta.model_validate(
        {
            "issuer_nif": "B12345674",
            "issuer_name": "TIENDA EJEMPLO SL",
            "number": "2026/000123",
            "issue_date": "2026-01-20",
            "type": "F2",
            "description": "Venta online - pedido 1234",
            "tax_lines": [{"rate": "21.00", "base": "82.64", "tax": "17.36"}],
            "total": "100.00",
        }
    )
    assert qr.url(alta, Environment.TEST) == CASES[1]["url"]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"nif": "B12345678"}, id="nif-checksum"),
        pytest.param({"number": "A=B"}, id="number-forbidden-char"),
        pytest.param({"total": Decimal("1.005")}, id="amount-three-decimals"),
    ],
)
def test_url_from_fields_validates(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "nif": "B12345674",
        "number": "2026-1",
        "issue_date": date(2026, 1, 20),
        "total": Decimal("1.00"),
        "env": Environment.TEST,
    } | overrides
    with pytest.raises(ValueError):  # noqa: PT011 - each case has its own message
        qr.url_from_fields(**fields)


def test_symbol_uses_error_correction_m_without_boost() -> None:
    code = qr.make(CASES[0]["url"])
    assert code.error == "M"
    assert not code.is_micro


def _png_chunks(png: bytes) -> dict[bytes, bytes]:
    chunks: dict[bytes, bytes] = {}
    pos = len(PNG_SIGNATURE)
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        chunks[kind] = png[pos + 8 : pos + 8 + length]
        pos += 12 + length
    return chunks


def test_png_symbol_is_35_mm_at_300_dpi() -> None:
    png = qr.png(CASES[0]["url"], size_mm=35, dpi=300)
    assert png.startswith(PNG_SIGNATURE)
    chunks = _png_chunks(png)
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    assert width == height
    modules = qr.make(CASES[0]["url"]).symbol_size(scale=1, border=0)[0]
    scale = width // (modules + 2 * qr.QUIET_ZONE_MODULES)
    symbol_mm = modules * scale / 300 * 25.4
    assert qr.MIN_SIZE_MM <= symbol_mm <= qr.MAX_SIZE_MM
    assert abs(symbol_mm - 35) < 1
    pixels_per_metre, _, unit = struct.unpack(">IIB", chunks[b"pHYs"])
    assert (round(pixels_per_metre * 0.0254), unit) == (300, 1)
    assert zlib.decompress(chunks[b"IDAT"])  # image data is a valid stream


def test_svg_symbol_is_exactly_the_requested_size() -> None:
    svg = qr.svg(CASES[0]["url"], size_mm=35).decode()
    modules = qr.make(CASES[0]["url"]).symbol_size(scale=1, border=0)[0]
    total_mm = 35 * (modules + 2 * qr.QUIET_ZONE_MODULES) / modules
    match = re.search(r'width="([0-9.]+)mm"', svg)
    assert match is not None, svg[:200]
    assert float(match.group(1)) == pytest.approx(total_mm)


@pytest.mark.parametrize("size_mm", [29, 41])
def test_size_outside_the_aeat_range_is_rejected(size_mm: float) -> None:
    with pytest.raises(ValueError, match="30"):
        qr.png(CASES[0]["url"], size_mm=size_mm)
    with pytest.raises(ValueError, match="30"):
        qr.svg(CASES[0]["url"], size_mm=size_mm)
