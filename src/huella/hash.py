"""The huella: SHA-256 chain hash of a billing record (AEAT huella spec v0.1.2, SPEC 3.4).

The input is ``name=value`` pairs joined by ``&``, in a fixed order, each value trimmed, encoded
as UTF-8. The output is 64 uppercase hex characters. Values must be the exact strings written to
the XML (see :mod:`huella.format`); the hash never re-formats anything.

Arguments are keyword-only: ``cuota`` and ``importe`` are both amount strings, and swapping them
positionally would produce a valid-looking but wrong hash.
"""

import hashlib

from huella.format import TIMESTAMP_PATTERN, format_amount, format_date
from huella.models import ChainLink, InvoiceAlta, InvoiceAnulacion

TIPO_HUELLA_SHA256 = "01"


def _sha256_upper(pairs: list[tuple[str, str]]) -> str:
    text = "&".join(f"{name}={value.strip()}" for name, value in pairs)
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def huella_alta(  # noqa: PLR0913 - one keyword-only argument per hashed field
    *,
    nif: str,
    num: str,
    fecha: str,
    tipo: str,
    cuota: str,
    importe: str,
    previa: str | None,
    ts: str,
) -> str:
    """Hash of a *registro de alta*. ``previa`` is ``None`` (or empty) for the first record.

    >>> huella_alta(nif="89890001K", num="12345678/G33", fecha="01-01-2024", tipo="F1",
    ...             cuota="12.35", importe="123.45", previa=None,
    ...             ts="2024-01-01T19:20:30+01:00")
    '3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60'
    """
    return _sha256_upper(
        [
            ("IDEmisorFactura", nif),
            ("NumSerieFactura", num),
            ("FechaExpedicionFactura", fecha),
            ("TipoFactura", tipo),
            ("CuotaTotal", cuota),
            ("ImporteTotal", importe),
            ("Huella", previa or ""),
            ("FechaHoraHusoGenRegistro", ts),
        ]
    )


def huella_anulacion(*, nif: str, num: str, fecha: str, previa: str | None, ts: str) -> str:
    """Hash of a *registro de anulación*. ``previa`` is ``None`` (or empty) for the first record.

    >>> huella_anulacion(nif="89890001K", num="12345679/G34", fecha="01-01-2024",
    ...     previa="F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97",
    ...     ts="2024-01-01T19:20:40+01:00")
    '177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68'
    """
    return _sha256_upper(
        [
            ("IDEmisorFacturaAnulada", nif),
            ("NumSerieFacturaAnulada", num),
            ("FechaExpedicionFacturaAnulada", fecha),
            ("Huella", previa or ""),
            ("FechaHoraHusoGenRegistro", ts),
        ]
    )


def hash_record(
    record: InvoiceAlta | InvoiceAnulacion, *, previous: ChainLink | None, ts: str
) -> str:
    """Huella of a validated record, chained to ``previous`` (``None`` for the first record).

    ``ts`` must be the exact text from :func:`huella.format.timestamp_madrid`; the same string
    goes into ``FechaHoraHusoGenRegistro`` in the XML.
    """
    if not TIMESTAMP_PATTERN.fullmatch(ts):
        raise ValueError(f"timestamp must come from timestamp_madrid(), got {ts!r}")
    previa = previous.huella if previous is not None else None
    fecha = format_date(record.issue_date)
    if isinstance(record, InvoiceAnulacion):
        return huella_anulacion(
            nif=record.issuer_nif, num=record.number, fecha=fecha, previa=previa, ts=ts
        )
    return huella_alta(
        nif=record.issuer_nif,
        num=record.number,
        fecha=fecha,
        tipo=record.type,
        cuota=format_amount(record.cuota_total),
        importe=format_amount(record.total),
        previa=previa,
        ts=ts,
    )
