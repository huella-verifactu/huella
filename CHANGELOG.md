# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is `0.x`, the API
may change in any minor release.

## [Unreleased]

### Added

- `huella.nif`: Spanish NIF, NIE and CIF checksum validation and normalisation.
- `huella.models`: immutable Pydantic models for altas, anulaciones and the SistemaInformatico
  block, enforcing the AEAT validations in scope (invoice number characters, dates, VAT rates,
  per-line tax within one cent, totals, recipients, corrective invoices, correction flags).
- `hash_record()`: the huella of a validated record.

## [0.0.1] - 2026-10-15

### Added

- `huella_alta()` and `huella_anulacion()`: the Verifactu record hash (*huella*), tested against
  the three official AEAT vectors and the known hash traps.
- `format_amount()`, `format_date()` and `timestamp_madrid()`: the exact text forms used in both
  the hash and the XML.
- `round_amount()`: rounding to cents, half away from zero, before formatting.
- The official AEAT XSD and WSDL files (spec version 1.0) in `huella/specs/v1_0/`.

[Unreleased]: https://github.com/huella-verifactu/huella/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/huella-verifactu/huella/releases/tag/v0.0.1
