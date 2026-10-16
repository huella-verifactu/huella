# Official AEAT sources (spec version 1.0)

Source: **Agencia Estatal de Administración Tributaria (AEAT)**, developer information for
VERI\*FACTU:
<https://www.agenciatributaria.es/AEAT.desarrolladores/Desarrolladores/_menu_/Documentacion/Sistemas_Informaticos_de_Facturacion_y_Sistemas_VERI_FACTU/Sistemas_Informaticos_de_Facturacion_y_Sistemas_VERI_FACTU.html>

Downloaded on **2026-10-15**. The files in this folder are **unmodified** copies. Do not edit
them. When the AEAT publishes a new version, add a new `specs/v1_x/` folder next to this one
instead of overwriting it.

Each file name below links to its official URL. `scripts/fetch_specs.py` reads this file (the
link, the date and the SHA-256 of each row), so keep one file per table row in that shape.

**Reuse conditions.** The AEAT legal notice ("Utilización de la información contenida en la web
de la Agencia Tributaria", page updated 13 Jan 2026) authorises reproduction and distribution of
the information on its website, for commercial and non-commercial use, provided the content is
not distorted, the source is cited and the date of last update is mentioned when available. The
"Last updated" column below is the HTTP `Last-Modified` date the AEAT server reported on
2026-10-15.

## Schemas and WSDL (shipped with the package; needed at runtime for validation)

| File | Last updated (AEAT) | SHA-256 |
|---|---|---|
| [`SistemaFacturacion.wsdl`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SistemaFacturacion.wsdl) | 2025-11-05 | `05919120708ff7650612fa6683c9336eaf919335d9a4db10e86759190af48602` |
| [`SuministroLR.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd) | 2025-10-01 | `cbdac8d427cc5ab5d77ca48974cab0f35d6bb819c4c66db361681e3710aeba36` |
| [`SuministroInformacion.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd) | 2026-01-11 | `ee4c1655175644de44c4c25055ffeb8e5f4bb4bc3834ce8254d4222ef18c8aa1` |
| [`RespuestaSuministro.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RespuestaSuministro.xsd) | 2025-10-01 | `82acf80f785643caac13087aae66808ed721a13f08ca5218cf8ae81b695549ef` |
| [`ConsultaLR.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/ConsultaLR.xsd) | 2025-11-05 | `bf2cdb8fc4b95b291757a72b76d8fffca06a6d30d9329122ca2fd6b2d5f8f1b1` |
| [`RespuestaConsultaLR.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RespuestaConsultaLR.xsd) | 2025-11-05 | `de35063acb8d9ba0d6ae51acc6b595de9c2b12333250e95e13108ef5f2670d45` |
| [`EventosSIF.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/EventosSIF.xsd) | 2025-10-01 | `cc7347c6a9a57a0c8edbc6b9ddcce55176452d0db0e68369477e207e9fbdd7e7` |
| [`RespuestaValRegistNoVeriFactu.xsd`](https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RespuestaValRegistNoVeriFactu.xsd) | 2025-10-01 | `8f47af4f3c49d29b6a62aed261c09f171e855ad6d6bb72ef3fc0b147dc9572f0` |

`SuministroInformacion.xsd` imports the W3C XML Signature schema by absolute URL. A local,
unmodified copy is kept so validation never touches the network. It is published by the W3C under
the W3C Software and Document License:

| File | Last updated | SHA-256 |
|---|---|---|
| [`xmldsig-core-schema.xsd`](https://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd) | 2013-04-16 | `d102ad3df7664c307e0c2c776ba4a90513b1969974d8a940bae1a77f9f21e15d` |

Week 1 note: the xmldsig schema starts with a `DOCTYPE` pointing at `XMLSchema.dtd`, and the AEAT
XSDs reference it by absolute URL. `huella.xml` must load them through a local resolver (or an XML
catalog) with network access disabled.

## Reference documents (not committed; fetch them with `scripts/fetch_specs.py`)

These are not needed at runtime. `uv run python scripts/fetch_specs.py` downloads them into
`docs/aeat/` (gitignored) and checks the SHA-256 values and `Last-Modified` dates below.

| File | What | Last updated (AEAT) | SHA-256 |
|---|---|---|---|
| [`Veri-Factu_especificaciones_huella_hash_registros.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Veri-Factu_especificaciones_huella_hash_registros.pdf) | Huella spec v0.1.2; test vectors in §6 | 2024-10-08 | `f4334c254bb875b417247b54315199f89d75a8c4814dfd1e86efec562653d7de` |
| [`DetalleEspecificacTecnCodigoQRfactura.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/DetalleEspecificacTecnCodigoQRfactura.pdf) | QR spec (URL, size, ECC level, legends) | 2025-12-18 | `f86b3c260d8a4963dbc18c5007732b53199156c5d1db63242e68db71501b49eb` |
| [`Veri-Factu_Descripcion_SWeb.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Veri-Factu_Descripcion_SWeb.pdf) | Web service description (flow control, responses) | 2025-10-14 | `b3570f6a308ce98a5f52001a0dc427310ad6cf7bccd60a9ee98720a59e553c02` |
| [`Validaciones_Errores_Veri-Factu.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Validaciones_Errores_Veri-Factu.pdf) | Business validations and error codes | 2026-04-08 | `426eb926fc098a36a163f66ca5f40d9e0847ca23300bbe5008979832d3513440` |
| [`FAQs-Desarrolladores.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/FAQs-Desarrolladores.pdf) | Developer FAQ | 2025-12-10 | `73906dc8afbbb9da35f6cb489980352b42aed66d48828fd62a00168883c09d5e` |
| [`EjemplosDeclaracionResponsable.pdf`](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/EjemplosDeclaracionResponsable.pdf) | Examples of the *declaración responsable* | 2025-06-17 | `1b8ce1de0593030952b650dee241fe1f449df841d1c3cd0c627a0f188214c063` |
| [`errores.properties`](https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/errores.properties) (ISO-8859-1) | Error code list | 2026-07-30 | `06519ceb23422bd6b0ad3bfb659e3007615050da4920781d12cff536481d5902` |

## Drift check

`uv run python scripts/fetch_specs.py` downloads every file listed here. It compares each
schema and the WSDL byte for byte with the committed copy, and each reference document with the
SHA-256 and `Last-Modified` date recorded above. The `spec-drift` workflow runs it every morning
and opens an issue when anything changed. Exit codes: `0` nothing changed, `3` drift, `4` could
not check (a network failure, never reported as drift).

When a file changed: read the new version (saved in `docs/aeat/`). A changed schema or WSDL goes
into a new `specs/v1_x/` folder, never into this one, followed by a minor release; records
already built keep the XML they were built with. For a reference document, or a new
`Last-Modified` date on identical content, update its row here.
