"""Huella: open-source Verifactu core (formatting, record hash, XML, QR, AEAT client)."""

from importlib.metadata import version

from huella.format import format_amount, format_date, round_amount, timestamp_madrid
from huella.hash import huella_alta, huella_anulacion

__version__ = version("huella")  # single source of truth: pyproject.toml

__all__ = [
    "__version__",
    "format_amount",
    "format_date",
    "huella_alta",
    "huella_anulacion",
    "round_amount",
    "timestamp_madrid",
]
