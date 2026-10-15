"""Huella: open-source Verifactu core (formatting, record hash, XML, QR, AEAT client)."""

from importlib.metadata import version

from huella.format import format_amount, format_date, round_amount, timestamp_madrid
from huella.hash import hash_record, huella_alta, huella_anulacion
from huella.models import (
    ChainLink,
    Correction,
    Environment,
    InvoiceAlta,
    InvoiceAnulacion,
    Recipient,
    Rectification,
    SistemaInformatico,
    TaxLine,
)
from huella.nif import is_valid_nif, validate_nif

__version__ = version("huella")  # single source of truth: pyproject.toml

__all__ = [
    "ChainLink",
    "Correction",
    "Environment",
    "InvoiceAlta",
    "InvoiceAnulacion",
    "Recipient",
    "Rectification",
    "SistemaInformatico",
    "TaxLine",
    "__version__",
    "format_amount",
    "format_date",
    "hash_record",
    "huella_alta",
    "huella_anulacion",
    "is_valid_nif",
    "round_amount",
    "timestamp_madrid",
    "validate_nif",
]
