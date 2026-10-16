# Contributing to huella

Thanks for helping. Bug reports, spec questions and pull requests are all welcome.

## Before you start

- **Security problems:** do not open a public issue. Follow [SECURITY.md](SECURITY.md).
- **Questions about the AEAT specification:** open an issue with the *Spec question* template and
  quote the official document and section you are reading.
- **Larger changes:** open an issue first so we can agree on the approach.

## Development

You need [uv](https://docs.astral.sh/uv/) and Python 3.12.

```sh
uv sync
uv run pytest --cov                     # tests, doctests and coverage (gate: 90%)
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/fetch_specs.py    # optional: AEAT files into docs/aeat/, reports drift
```

Install the pre-commit hooks once. They run [gitleaks](https://github.com/gitleaks/gitleaks) so a
certificate, key or password can never be committed by accident:

```sh
uv tool install pre-commit
pre-commit install
```

## Rules

- Every change to formatting, hashing or XML needs a test, and the official AEAT vectors must keep
  passing.
- Money is never a `float`. Use `Decimal`.
- Never commit certificates, keys, passwords or real taxpayer data. Use the AEAT's example NIF
  `89890001K` or synthetic NIFs. Anonymise recorded AEAT responses before committing them.
- The files in `src/huella/specs/` are official AEAT files and are never edited.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## Licence and sign-off

Contributions are accepted under the project's licence, Apache-2.0 (inbound = outbound). There is
no CLA. Instead, every commit must carry a
[Developer Certificate of Origin](https://developercertificate.org/) sign-off, which you add with:

```sh
git commit -s
```
