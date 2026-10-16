"""Download the official files listed in SOURCES.md and report any drift (SPEC 11.5).

Every file in the ``SOURCES.md`` of the spec folder the code uses (``huella.xml.SPECS``) is
downloaded from its official URL and saved in ``docs/aeat/`` (gitignored):

- schemas and the WSDL are compared byte for byte with the committed copy;
- reference documents (PDFs, ``errores.properties``), never committed, are compared with the
  SHA-256 recorded in SOURCES.md;
- for both, the HTTP ``Last-Modified`` date is compared with the recorded date.

Run from the ``core`` folder:

    uv run python scripts/fetch_specs.py

Exit codes: 0 nothing changed, 3 drift, 4 could not check (a network failure is never drift).
Any other non-zero code (1 a Python error, 2 a usage error) means the check itself is broken.
"""

import argparse
import hashlib
import http.client
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path

from huella.xml import SPECS

TIMEOUT_S = 60
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "docs" / "aeat"
COMMITTED_SUFFIXES = (".xsd", ".wsdl")
# A file no longer at its URL was moved or withdrawn: that is drift, not a network failure.
GONE_HTTP_STATUSES = frozenset({404, 410})

EXIT_OK = 0
EXIT_DRIFT = 3
EXIT_UNCHECKED = 4

LINKED_CELL = "](https://"
# | [`name`](https://url) optional note | other columns... | YYYY-MM-DD | `sha256` |
ROW = re.compile(
    r"^\| \[`(?P<name>[^`/\\]+)`\]\((?P<url>https://[^)\s]+)\)"
    r".*\| (?P<date>\d{4}-\d{2}-\d{2}) \| `(?P<sha256>[0-9a-f]{64})` \|$"
)


@dataclass(frozen=True)
class Source:
    """One row of SOURCES.md."""

    name: str
    url: str
    last_modified: date
    sha256: str

    @property
    def committed(self) -> bool:
        """Schemas and the WSDL are committed; reference documents are not."""
        return self.name.endswith(COMMITTED_SUFFIXES)


@dataclass(frozen=True)
class Download:
    body: bytes
    last_modified: date | None


class Status(StrEnum):
    OK = "ok"
    CHANGED = "CHANGED"
    UNCHECKED = "UNCHECKED"


@dataclass(frozen=True)
class Result:
    name: str
    status: Status
    detail: str = ""


class GoneError(Exception):
    """The server says the file is no longer at its URL."""


class UnreachableError(Exception):
    """The file could not be downloaded, so nothing is known about it."""


def parse_sources(text: str) -> list[Source]:
    """Read the file rows of SOURCES.md. A row that looks like a file but does not parse fails."""
    sources = []
    for line in text.splitlines():
        if not (line.startswith("|") and LINKED_CELL in line):
            continue
        match = ROW.match(line)
        if match is None:
            raise ValueError(f"unreadable SOURCES.md row: {line}")
        sources.append(
            Source(match["name"], match["url"], date.fromisoformat(match["date"]), match["sha256"])
        )
    if not sources:
        raise ValueError("SOURCES.md lists no files")
    return sources


def http_date(value: str | None) -> date | None:
    """The date of an HTTP date header, or None if it is missing or malformed."""
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def download(url: str) -> Download:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310 - https URLs from SOURCES.md
            body: bytes = response.read()
            last_modified = http_date(response.headers.get("Last-Modified"))
    except urllib.error.HTTPError as exc:
        if exc.code in GONE_HTTP_STATUSES:
            raise GoneError(f"no longer at its URL (HTTP {exc.code})") from exc
        raise UnreachableError(f"HTTP {exc.code}") from exc
    except (OSError, http.client.HTTPException) as exc:  # DNS, refused, reset, timeout, TLS
        raise UnreachableError(str(exc) or type(exc).__name__) from exc
    return Download(body, last_modified)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare(source: Source, got: Download, committed: bytes | None) -> Result:
    """Compare a download with the committed copy (schemas) or the recorded SHA-256 (documents)."""
    expected = sha256(committed) if committed is not None else source.sha256
    against = "the committed copy" if committed is not None else "the recorded SHA-256"
    actual = sha256(got.body)
    if actual != expected:
        return Result(source.name, Status.CHANGED, f"content differs from {against} (now {actual})")
    if got.last_modified is not None and got.last_modified != source.last_modified:
        return Result(
            source.name,
            Status.CHANGED,
            f"same content, but Last-Modified is now {got.last_modified} "
            f"(recorded {source.last_modified})",
        )
    return Result(source.name, Status.OK)


def check(source: Source, fetch: Callable[[str], Download], specs_dir: Path, dest: Path) -> Result:
    try:
        got = fetch(source.url)
    except GoneError as exc:
        return Result(source.name, Status.CHANGED, str(exc))
    except UnreachableError as exc:
        return Result(source.name, Status.UNCHECKED, f"could not check: {exc}")
    (dest / source.name).write_bytes(got.body)
    committed = (specs_dir / source.name).read_bytes() if source.committed else None
    return compare(source, got, committed)


def exit_code(results: Sequence[Result]) -> int:
    statuses = {result.status for result in results}
    if Status.CHANGED in statuses:
        return EXIT_DRIFT
    if Status.UNCHECKED in statuses:
        return EXIT_UNCHECKED
    return EXIT_OK


def report(results: Sequence[Result], dest: Path) -> str:
    lines = [
        f"{result.status:9} {result.name}" + (f": {result.detail}" if result.detail else "")
        for result in results
    ]
    changed = [result.name for result in results if result.status is Status.CHANGED]
    unchecked = [result.name for result in results if result.status is Status.UNCHECKED]
    if changed:
        lines += [
            "",
            f"Drift in {len(changed)} file(s): {', '.join(changed)}.",
            f"Read the new version(s) in {dest}. A changed schema or WSDL goes into a new",
            "specs/v1_x/ folder (never edit the current one) and a minor release; for a",
            "reference document or a new date only, update its row in SOURCES.md.",
        ]
    if unchecked:
        lines += [
            "",
            f"Could not check {len(unchecked)} file(s): {', '.join(unchecked)}.",
            "This is not drift: the download failed. Run the check again later.",
        ]
    if not changed and not unchecked:
        lines += ["", f"No drift: all {len(results)} files match SOURCES.md."]
    return "\n".join(lines)


def main(argv: list[str] | None = None, fetch: Callable[[str], Download] = download) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--sources", type=Path, default=SPECS / "SOURCES.md", help="SOURCES.md to check"
    )
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="download folder")
    args = parser.parse_args(argv)
    sources_path: Path = args.sources
    dest: Path = args.dest

    sources = parse_sources(sources_path.read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    results = [check(source, fetch, sources_path.parent, dest) for source in sources]
    print(report(results, dest))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
