# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is `0.x`, the API
may change in any minor release.

## [Unreleased]

### Added

- AEAT spec drift check: `scripts/fetch_specs.py` downloads every official file listed in
  `specs/v1_0/SOURCES.md` and compares the schemas and WSDL byte for byte with the committed
  copies, and the reference documents with their recorded SHA-256 and `Last-Modified` date. Exit
  `3` is drift, `4` "could not check" (a network failure is never reported as drift). The
  `spec-drift` workflow runs it every morning and opens an issue on drift.

## [0.2.0] - 2026-10-16

### Changed

- The tax of each tax line may now differ from base x rate by up to **1.00** (was 0.01). Shops
  that round tax per order line, as WooCommerce does by default, drift by up to half a cent per
  line, and the stricter rule refused correct invoices. Still ten times stricter than the AEAT's
  10.00; rates other than 21, 10 and 4 % are refused as before.
- `AeatClient` raises `CertificateError` only for TLS alerts about the client certificate (bad,
  unknown CA, required, expired, revoked, unknown, unsupported). Every other TLS failure, above
  all a failure to verify the AEAT's own certificate, is now a retryable `TransportError`: it is
  not the taxpayer's certificate that is wrong.

## [0.1.0] - 2026-10-15

### Added

- `huella.nif`: Spanish NIF, NIE and CIF checksum validation and normalisation.
- `huella.models`: immutable Pydantic models for altas, anulaciones and the SistemaInformatico
  block, enforcing the AEAT validations in scope (invoice number characters, dates, VAT rates,
  per-line tax within one cent, totals, recipients, corrective invoices, correction flags).
- `hash_record()`: the huella of a validated record.
- `huella.qr`: the AEAT validation URL (RFC 3986 encoding, shared fixture with the plugin) and
  PNG/SVG images with error correction M, 30-40 mm and a 4-module quiet zone.
- `Environment` (test / production).
- `huella.xml`: `registro_alta()`, `registro_anulacion()` and `envelope()` build the AEAT XML in
  XSD order and validate it against the bundled official XSD before returning (offline). Stored
  records are re-parsed without DTDs, entities or network access.
- `huella.errors`: `HuellaError`, `SchemaError`, `TransportError`, `CertificateError`, `AeatFault`.
- `huella.aeat`: endpoints from the WSDL, `client_ssl_context()` for mutual TLS, `AeatClient.send()`
  and `parse_response()` (per-record status, error codes, duplicates, CSV, `TiempoEsperaEnvio`).
- Development CLI `huella hash | xml | send` over a batch JSON file (`examples/batch.json`);
  `.p12`/`.pfx` support via the `cli` extra; production sends need `--yes-production`.

## [0.0.1] - 2026-10-15

### Added

- `huella_alta()` and `huella_anulacion()`: the Verifactu record hash (*huella*), tested against
  the three official AEAT vectors and the known hash traps.
- `format_amount()`, `format_date()` and `timestamp_madrid()`: the exact text forms used in both
  the hash and the XML.
- `round_amount()`: rounding to cents, half away from zero, before formatting.
- The official AEAT XSD and WSDL files (spec version 1.0) in `huella/specs/v1_0/`.

[Unreleased]: https://github.com/huella-verifactu/huella/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/huella-verifactu/huella/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/huella-verifactu/huella/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/huella-verifactu/huella/releases/tag/v0.0.1
