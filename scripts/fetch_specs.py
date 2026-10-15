"""Download the AEAT reference documents into docs/aeat/ and check their SHA-256 (SPEC 11.5).

The PDFs and the error list are not committed; only the XSD/WSDL files the code needs at
runtime are (``src/huella/specs/v1_0/``). Run from the ``core`` folder:

    uv run python scripts/fetch_specs.py

A hash mismatch means the AEAT published a new version. The new file is still saved so you can
read what changed; update the hash here and in ``SOURCES.md`` only after that.
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

PDF_BASE = "https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/"
ERRORS_URL = (
    "https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/"
    "tikeV1.0/cont/ws/errores.properties"
)
TIMEOUT_S = 60
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "docs" / "aeat"

# filename -> (url, expected SHA-256), as downloaded on 2026-10-15
DOCUMENTS: dict[str, tuple[str, str]] = {
    "Veri-Factu_especificaciones_huella_hash_registros.pdf": (
        PDF_BASE + "Veri-Factu_especificaciones_huella_hash_registros.pdf",
        "f4334c254bb875b417247b54315199f89d75a8c4814dfd1e86efec562653d7de",
    ),
    "DetalleEspecificacTecnCodigoQRfactura.pdf": (
        PDF_BASE + "DetalleEspecificacTecnCodigoQRfactura.pdf",
        "f86b3c260d8a4963dbc18c5007732b53199156c5d1db63242e68db71501b49eb",
    ),
    "Veri-Factu_Descripcion_SWeb.pdf": (
        PDF_BASE + "Veri-Factu_Descripcion_SWeb.pdf",
        "b3570f6a308ce98a5f52001a0dc427310ad6cf7bccd60a9ee98720a59e553c02",
    ),
    "Validaciones_Errores_Veri-Factu.pdf": (
        PDF_BASE + "Validaciones_Errores_Veri-Factu.pdf",
        "426eb926fc098a36a163f66ca5f40d9e0847ca23300bbe5008979832d3513440",
    ),
    "FAQs-Desarrolladores.pdf": (
        PDF_BASE + "FAQs-Desarrolladores.pdf",
        "73906dc8afbbb9da35f6cb489980352b42aed66d48828fd62a00168883c09d5e",
    ),
    "EjemplosDeclaracionResponsable.pdf": (
        PDF_BASE + "EjemplosDeclaracionResponsable.pdf",
        "1b8ce1de0593030952b650dee241fe1f449df841d1c3cd0c627a0f188214c063",
    ),
    "errores.properties": (
        ERRORS_URL,
        "06519ceb23422bd6b0ad3bfb659e3007615050da4920781d12cff536481d5902",
    ),
}


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https URLs
        data: bytes = response.read()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="output folder")
    args = parser.parse_args(argv)
    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []
    for name, (url, expected) in DOCUMENTS.items():
        data = download(url)
        (dest / name).write_bytes(data)
        matches = hashlib.sha256(data).hexdigest() == expected
        print(f"{'ok' if matches else 'CHANGED':8} {name}")
        if not matches:
            changed.append(name)

    if changed:
        print(
            f"\n{len(changed)} file(s) differ from the recorded version. The AEAT may have "
            f"published an update: read the new file(s) in {dest} before updating the hashes.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
