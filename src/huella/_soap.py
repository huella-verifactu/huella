"""Reading SOAP answers from the AEAT safely: shared by the submission and the consulta parsers."""

import re

from lxml import etree

from huella.errors import AeatFault, TransportError

_FAULT_CODE = re.compile(r"Codigo\[(\d+)\]")


def parse_xml(body: bytes) -> etree._Element:
    """The answer as XML, refusing anything that is not plain XML (no DTD, no entities)."""
    parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=False)
    try:
        root = etree.fromstring(body, parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise TransportError(f"the AEAT answer is not XML: {exc}") from exc
    if root.getroottree().docinfo.doctype:
        raise TransportError("the AEAT answer contains a DOCTYPE; refused")
    return root


def fault(element: etree._Element) -> AeatFault:
    """A SOAP fault as an exception, with the AEAT error code when the message carries one."""
    faultcode = (element.findtext("faultcode") or "unknown").strip()
    message = " ".join((element.findtext("faultstring") or "").split())
    match = _FAULT_CODE.search(message)
    return AeatFault(faultcode, message, int(match.group(1)) if match else None)
