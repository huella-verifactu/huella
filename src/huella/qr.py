"""The AEAT QR code: validation URL and image (AEAT QR spec; SPEC 3.7).

The QR depends only on NIF, number, date and total, never on the huella, so an invoice can carry
it before its record reaches the AEAT (D7). The WooCommerce plugin builds the same URL in PHP;
``tests/fixtures/qr_cases.json`` keeps both byte-identical.

Values are percent-encoded per RFC 3986 (``quote(value, safe="")``, PHP ``rawurlencode``). This is
the only place encoding is used: the hash and the XML take the raw values.
"""

import io
from datetime import date
from decimal import Decimal
from urllib.parse import quote

import segno

from huella.format import format_amount, format_date
from huella.models import Environment, InvoiceAlta, check_invoice_number
from huella.nif import validate_nif

HOSTS = {
    Environment.TEST: "https://prewww2.aeat.es",
    Environment.PRODUCTION: "https://www2.agenciatributaria.gob.es",
}
PATH = "/wlpl/TIKE-CONT/ValidarQR"

MIN_SIZE_MM = 30  # AEAT: between 30x30 and 40x40 mm
MAX_SIZE_MM = 40
DEFAULT_SIZE_MM = 35
QUIET_ZONE_MODULES = 4  # ISO/IEC 18004 minimum; added around the symbol, not counted in its size
MM_PER_INCH = 25.4


def url_from_fields(
    *, nif: str, number: str, issue_date: date, total: Decimal, env: Environment
) -> str:
    """Validation URL from raw fields; each one is validated first.

    >>> url_from_fields(nif="B12345674", number="2026/1", issue_date=date(2026, 1, 20),
    ...                 total=Decimal("100"), env=Environment.TEST)
    'https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR?nif=B12345674&numserie=2026%2F1&fecha=20-01-2026&importe=100.00'
    """
    params = {
        "nif": validate_nif(nif),
        "numserie": check_invoice_number(number),
        "fecha": format_date(issue_date),
        "importe": format_amount(total),
    }
    query = "&".join(f"{name}={quote(value, safe='')}" for name, value in params.items())
    return f"{HOSTS[env]}{PATH}?{query}"


def url(alta: InvoiceAlta, env: Environment) -> str:
    """Validation URL of a validated invoice."""
    return url_from_fields(
        nif=alta.issuer_nif,
        number=alta.number,
        issue_date=alta.issue_date,
        total=alta.total,
        env=env,
    )


def make(content: str) -> segno.QRCode:
    """QR symbol with error correction level M, never boosted to a higher level (AEAT spec)."""
    return segno.make_qr(content, error="m", boost_error=False)


def _modules(code: segno.QRCode) -> int:
    return int(code.symbol_size(scale=1, border=0)[0])


def _check_size(size_mm: float) -> None:
    if not MIN_SIZE_MM <= size_mm <= MAX_SIZE_MM:
        raise ValueError(
            f"the AEAT requires a QR code between {MIN_SIZE_MM} and {MAX_SIZE_MM} mm, got {size_mm}"
        )


def png(content: str, *, size_mm: float = DEFAULT_SIZE_MM, dpi: int = 300) -> bytes:
    """PNG with the symbol as close to ``size_mm`` as whole pixels allow, plus the quiet zone."""
    _check_size(size_mm)
    code = make(content)
    modules = _modules(code)
    scale = max(1, round(size_mm / MM_PER_INCH * dpi / modules))
    _check_size(modules * scale / dpi * MM_PER_INCH)  # whole pixels must stay within range
    out = io.BytesIO()
    code.save(out, kind="png", scale=scale, border=QUIET_ZONE_MODULES, dpi=dpi)
    return out.getvalue()


def svg(content: str, *, size_mm: float = DEFAULT_SIZE_MM) -> bytes:
    """SVG in millimetres with the symbol exactly ``size_mm`` wide, plus the quiet zone."""
    _check_size(size_mm)
    code = make(content)
    out = io.BytesIO()
    code.save(
        out,
        kind="svg",
        scale=size_mm / _modules(code),
        border=QUIET_ZONE_MODULES,
        unit="mm",
        xmldecl=False,
    )
    return out.getvalue()
