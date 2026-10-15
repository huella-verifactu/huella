"""Exceptions raised by huella (SPEC 4.3).

Invalid user input surfaces earlier, as ``pydantic.ValidationError`` from :mod:`huella.models`.
"""


class HuellaError(Exception):
    """Base class for huella's own errors."""


class SchemaError(HuellaError):
    """A document failed validation against the official AEAT XSD. Always a bug in huella."""
