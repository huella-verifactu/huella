"""Exceptions raised by huella (SPEC 4.3).

Invalid user input surfaces earlier, as ``pydantic.ValidationError`` from :mod:`huella.models`.
"""


class HuellaError(Exception):
    """Base class for huella's own errors."""


class SchemaError(HuellaError):
    """A document failed validation against the official AEAT XSD. Always a bug in huella."""


class TransportError(HuellaError):
    """The request may not have reached the AEAT, or its answer was unusable. Retry later."""


class CertificateError(HuellaError):
    """The client certificate could not be loaded or was refused. Retrying will not help."""


class AeatFault(HuellaError):  # noqa: N818 - name fixed by SPEC 4.3
    """The AEAT refused the whole request with a SOAP fault.

    ``env:Server`` faults are retryable (resend unchanged); ``env:Client`` faults mean the
    request or its header is wrong and must be fixed first (Veri-Factu_Descripcion_SWeb 5.1).
    """

    def __init__(self, faultcode: str, message: str, code: int | None) -> None:
        super().__init__(f"{faultcode}: {message}")
        self.faultcode = faultcode
        self.message = message
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.faultcode.rsplit(":", 1)[-1] == "Server"
