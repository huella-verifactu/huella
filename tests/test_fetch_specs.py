"""AEAT spec drift check (scripts/fetch_specs.py, SPEC 11.5). No network: fetch is faked."""

import hashlib
import http.client
import io
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from fetch_specs import (
    EXIT_DRIFT,
    EXIT_OK,
    EXIT_UNCHECKED,
    Download,
    GoneError,
    Result,
    Source,
    Status,
    UnreachableError,
    check,
    compare,
    download,
    exit_code,
    http_date,
    main,
    parse_sources,
    tls_context,
)
from huella.xml import SPECS

SCHEMA = b"<xs:schema/>"
PDF = b"%PDF-1.7 reference"
RECORDED = date(2025, 10, 1)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source(name: str, data: bytes = PDF, recorded: date = RECORDED) -> Source:
    return Source(name, f"https://aeat.example/{name}", recorded, sha(data))


def row(src: Source, note: str = "") -> str:
    return f"| [`{src.name}`]({src.url}){note} | What | {src.last_modified} | `{src.sha256}` |"


# --- SOURCES.md -------------------------------------------------------------------------------


def test_parses_every_row_of_the_committed_sources() -> None:
    sources = parse_sources((SPECS / "SOURCES.md").read_text(encoding="utf-8"))

    names = {s.name for s in sources if s.committed}
    assert names == {p.name for p in SPECS.iterdir() if p.suffix in {".xsd", ".wsdl"}}
    assert {s.name for s in sources if not s.committed} >= {"errores.properties"}
    assert all(s.url.startswith("https://") and s.url.endswith(s.name) for s in sources)


def test_committed_files_match_their_recorded_sha256() -> None:
    sources = parse_sources((SPECS / "SOURCES.md").read_text(encoding="utf-8"))

    for src in sources:
        if src.committed:
            assert sha((SPECS / src.name).read_bytes()) == src.sha256, src.name


def test_parses_a_row_with_a_note_after_the_link() -> None:
    src = source("errores.properties")

    assert parse_sources(row(src, note=" (ISO-8859-1)")) == [src]


@pytest.mark.parametrize(
    "line",
    [
        "| [`a.xsd`](https://x/a.xsd) | 2025-10-01 | `not-a-hash` |",
        "|[`a.xsd`](https://x/a.xsd) | 2025-10-01 | `" + "0" * 64 + "` |",
        "| [a.xsd](https://x/a.xsd) | 2025-10-01 | `" + "0" * 64 + "` |",
    ],
)
def test_rejects_a_file_row_it_cannot_read(line: str) -> None:
    with pytest.raises(ValueError, match="unreadable"):
        parse_sources(line)


def test_rejects_sources_without_files() -> None:
    with pytest.raises(ValueError, match="no files"):
        parse_sources("# Nothing here\n| File | SHA-256 |")


# --- Comparison ------------------------------------------------------------------------------


def test_committed_schema_identical_is_ok() -> None:
    result = compare(source("a.xsd", SCHEMA), Download(SCHEMA, RECORDED), committed=SCHEMA)

    assert result == Result("a.xsd", Status.OK)


def test_committed_schema_compares_with_the_committed_bytes_not_the_recorded_hash() -> None:
    stale = Source("a.xsd", "https://x/a.xsd", RECORDED, sha(b"old"))

    result = compare(stale, Download(SCHEMA, RECORDED), committed=b"<xs:schema />")

    assert result.status is Status.CHANGED
    assert "committed copy" in result.detail


def test_reference_document_with_a_new_hash_is_drift() -> None:
    result = compare(source("a.pdf"), Download(b"new pdf", RECORDED), committed=None)

    assert result.status is Status.CHANGED
    assert "recorded SHA-256" in result.detail
    assert sha(b"new pdf") in result.detail


def test_same_content_with_a_new_last_modified_is_drift() -> None:
    result = compare(source("a.pdf"), Download(PDF, date(2026, 11, 2)), committed=None)

    assert result.status is Status.CHANGED
    assert "2026-11-02" in result.detail
    assert "2025-10-01" in result.detail


def test_missing_last_modified_compares_content_only() -> None:
    assert compare(source("a.pdf"), Download(PDF, None), committed=None).status is Status.OK


# --- One file --------------------------------------------------------------------------------


def fetch_raising(exc: Exception) -> Callable[[str], Download]:
    def fetch(url: str) -> Download:
        raise exc

    return fetch


def test_check_saves_the_download_and_compares_with_the_committed_copy(tmp_path: Path) -> None:
    specs, dest = tmp_path / "specs", tmp_path / "dest"
    specs.mkdir()
    dest.mkdir()
    (specs / "a.xsd").write_bytes(SCHEMA)

    result = check(source("a.xsd", SCHEMA), lambda url: Download(SCHEMA, None), specs, dest)

    assert result.status is Status.OK
    assert (dest / "a.xsd").read_bytes() == SCHEMA


def test_network_failure_is_could_not_check_not_drift(tmp_path: Path) -> None:
    result = check(
        source("a.pdf"), fetch_raising(UnreachableError("timed out")), tmp_path, tmp_path
    )

    assert result == Result("a.pdf", Status.UNCHECKED, "could not check: timed out")
    assert not (tmp_path / "a.pdf").exists()


def test_file_gone_from_its_url_is_drift(tmp_path: Path) -> None:
    result = check(source("a.pdf"), fetch_raising(GoneError("HTTP 404")), tmp_path, tmp_path)

    assert result == Result("a.pdf", Status.CHANGED, "HTTP 404")


# --- Exit code and report -----------------------------------------------------------------------

OK = Result("a.xsd", Status.OK)
CHANGED = Result("b.xsd", Status.CHANGED, "content differs")
UNCHECKED = Result("c.pdf", Status.UNCHECKED, "could not check: timed out")


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([OK], EXIT_OK),
        ([OK, UNCHECKED], EXIT_UNCHECKED),
        ([OK, CHANGED], EXIT_DRIFT),
        ([UNCHECKED, CHANGED], EXIT_DRIFT),  # drift wins: it needs action either way
    ],
)
def test_exit_code(results: list[Result], expected: int) -> None:
    assert exit_code(results) == expected


def test_exit_codes_never_collide_with_a_python_crash_or_usage_error() -> None:
    assert {EXIT_DRIFT, EXIT_UNCHECKED}.isdisjoint({1, 2})


# --- main --------------------------------------------------------------------------------------


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    folder = tmp_path / "v1_0"
    folder.mkdir()
    (folder / "a.xsd").write_bytes(SCHEMA)
    rows = [row(source("a.xsd", SCHEMA)), row(source("b.pdf")), row(source("c.pdf"))]
    (folder / "SOURCES.md").write_text("\n".join(["| File |", "|---|", *rows]), encoding="utf-8")
    return folder


def run(specs: Path, files: dict[str, bytes | Exception]) -> int:
    def fetch(url: str) -> Download:
        found = files[url.rsplit("/", 1)[1]]
        if isinstance(found, Exception):
            raise found
        return Download(found, RECORDED)

    sources = str(specs / "SOURCES.md")
    return main(["--sources", sources, "--dest", str(specs.parent / "out")], fetch=fetch)


def test_main_reports_no_drift(specs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(specs, {"a.xsd": SCHEMA, "b.pdf": PDF, "c.pdf": PDF}) == EXIT_OK
    assert "No drift: all 3 files match" in capsys.readouterr().out


def test_main_names_the_changed_and_unchecked_files(
    specs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files: dict[str, bytes | Exception] = {
        "a.xsd": b"<xs:schema version='1.1'/>",
        "b.pdf": PDF,
        "c.pdf": UnreachableError("timed out"),
    }

    assert run(specs, files) == EXIT_DRIFT
    out = capsys.readouterr().out
    assert "CHANGED   a.xsd: content differs from the committed copy" in out
    assert "Drift in 1 file(s): a.xsd." in out
    assert "specs/v1_x/" in out
    assert "UNCHECKED c.pdf: could not check: timed out" in out
    assert "Could not check 1 file(s): c.pdf." in out
    assert "This is not drift" in out


def test_main_network_failure_only(specs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files: dict[str, bytes | Exception] = {
        "a.xsd": SCHEMA,
        "b.pdf": PDF,
        "c.pdf": UnreachableError("timed out"),
    }

    assert run(specs, files) == EXIT_UNCHECKED
    assert "Drift in" not in capsys.readouterr().out


# --- download (urlopen faked) ------------------------------------------------------------------


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, last_modified: str | None) -> None:
        super().__init__(body)
        self.headers = Message()
        if last_modified is not None:
            self.headers["Last-Modified"] = last_modified


def fake_urlopen(monkeypatch: pytest.MonkeyPatch, outcome: FakeResponse | Exception) -> list[str]:
    calls: list[str] = []

    def urlopen(url: str, timeout: float, context: ssl.SSLContext) -> Any:
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


def test_download_reads_body_and_last_modified(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_urlopen(monkeypatch, FakeResponse(PDF, "Wed, 01 Oct 2025 08:07:26 GMT"))

    assert download("https://x/a.pdf") == Download(PDF, date(2025, 10, 1))
    assert calls == ["https://x/a.pdf"]


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/a.pdf", code, "error", Message(), None)


@pytest.mark.parametrize("code", [404, 410])
def test_download_gone(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    fake_urlopen(monkeypatch, http_error(code))

    with pytest.raises(GoneError, match=f"HTTP {code}"):
        download("https://x/a.pdf")


@pytest.mark.parametrize(
    "exc",
    [
        http_error(503),
        urllib.error.URLError("Name or service not known"),
        TimeoutError(),
        ConnectionResetError("reset by peer"),
    ],
)
def test_download_network_failure_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    fake_urlopen(monkeypatch, exc)

    with pytest.raises(UnreachableError):
        download("https://x/a.pdf")


def test_download_incomplete_read_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_urlopen(monkeypatch, http.client.IncompleteRead(b"partial"))

    with pytest.raises(UnreachableError, match="IncompleteRead"):
        download("https://x/a.pdf")


def test_legacy_tls_only_for_the_host_with_a_sha1_intermediate() -> None:
    legacy = tls_context("https://www.agenciatributaria.es/static_files/a.pdf")
    modern = tls_context("https://www2.agenciatributaria.gob.es/static_files/a.xsd")

    assert legacy.security_level == 0
    assert modern.security_level > 0
    for context in (legacy, modern):
        assert context.verify_mode is ssl.CERT_REQUIRED
        assert context.check_hostname


@pytest.mark.parametrize("value", [None, "", "not a date"])
def test_http_date_missing_or_malformed_is_none(value: str | None) -> None:
    assert http_date(value) is None
