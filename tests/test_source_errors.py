"""Behaviour when a source file cannot be read or parsed.

Reading a scanned file can fail for reasons that are not architecture findings:
the path may not be readable, the bytes may not be UTF-8, or the text may not
be valid Python. Every one of those is an input problem, so the run has to end
with a reported source error and the documented validation exit code rather
than a traceback from ``Path.read_text`` or ``ast.parse``.

These tests build real broken files, so they exercise the same code path a
scanned package takes rather than a mocked read.
"""

from __future__ import annotations

import typing as typ
from pathlib import Path

import pytest

from hecate.cli import main
from hecate.source import SourceError, parse_source

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


_CONFIG = """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "pkg"
prefixes = ["pkg"]
allowed = ["pkg"]
"""


def _write_package(root: Path, *, poisoned: str, contents: bytes) -> Path:
    """Write a one-file package whose module ``poisoned`` holds ``contents``.

    The package itself is otherwise valid, so a failure can only come from the
    poisoned file rather than from anything else in the scan.
    """
    package_root = root / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / poisoned).write_bytes(contents)
    config = root / "pyproject.toml"
    config.write_text(_CONFIG, encoding="utf-8")
    return config


def test_parse_source_rejects_bytes_that_are_not_utf8(tmp_path: Path) -> None:
    """Invalid UTF-8 is a source error naming the file, not a decode traceback."""
    source = tmp_path / "broken.py"
    source.write_bytes(b"x = 1\ny = '\xff\xfe'\n")

    with pytest.raises(SourceError) as exc_info:
        parse_source(source)

    assert str(source) in str(exc_info.value), (
        f"the error must name the unreadable file, got {exc_info.value!r}"
    )


def test_parse_source_rejects_text_that_is_not_valid_python(tmp_path: Path) -> None:
    """A syntax error reports its location so the file can be fixed."""
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(SourceError) as exc_info:
        parse_source(source)

    message = str(exc_info.value)
    assert str(source) in message, f"the error must name the file, got {message!r}"
    assert ":1" in message, f"the error must locate the fault, got {message!r}"


def test_parse_source_rejects_a_path_it_cannot_read(tmp_path: Path) -> None:
    """An unreadable path is a source error rather than a raw ``OSError``.

    A directory named like a module is the reproducible way to reach the read
    failure: it is matched by the package scan and cannot be read as text.
    """
    source = tmp_path / "unreadable.py"
    source.mkdir()

    with pytest.raises(SourceError) as exc_info:
        parse_source(source)

    assert str(source) in str(exc_info.value), (
        f"the error must name the unreadable path, got {exc_info.value!r}"
    )


def test_parse_source_returns_a_tree_for_valid_source(tmp_path: Path) -> None:
    """The boundary is transparent for a healthy file.

    Without this control the error tests would pass even if ``parse_source``
    rejected everything.
    """
    source = tmp_path / "fine.py"
    source.write_text("x = 1\n", encoding="utf-8")

    tree = parse_source(source)

    assert [node.lineno for node in tree.body] == [1], (
        f"a valid module must parse into its statements, got {tree.body!r}"
    )


@pytest.mark.parametrize(
    "case",
    [
        ("bad_utf8.py", b"y = '\xff\xfe'\n"),
        ("bad_syntax.py", b"def broken(:\n"),
    ],
    ids=("bad-utf8", "bad-syntax"),
)
def test_cli_reports_unparsable_source_with_the_validation_exit_code(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    case: tuple[str, bytes],
) -> None:
    """A scanned file hecate cannot parse fails the run as an input error.

    Exit code 2 is the documented "input validation failed" result. Reporting
    the file on stderr keeps the failure actionable, and keeps a broken
    checkout from being mistaken for an architecture violation at exit 1.
    """
    poisoned, contents = case
    config = _write_package(tmp_path, poisoned=poisoned, contents=contents)

    exit_code = main(["check", "--config", str(config)])

    captured = capsys.readouterr()
    assert exit_code == 2, (
        f"{poisoned}: an unparsable scanned file must be an input error, "
        f"got exit code {exit_code} with {captured!r}"
    )
    assert poisoned in captured.err, (
        f"{poisoned}: stderr must name the file to fix, got {captured.err!r}"
    )


def test_cli_reports_an_unreadable_scanned_path(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A path the scan cannot read is reported instead of crashing the run.

    The package root is walked for ``*.py``, which also matches a directory of
    that name. Reading one fails, and the run must say so rather than letting
    the underlying filesystem error escape as a traceback.
    """
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "unreadable.py").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(_CONFIG, encoding="utf-8")

    exit_code = main(["check", "--config", str(config)])

    captured = capsys.readouterr()
    assert exit_code == 2, (
        f"an unreadable scanned path must be an input error, got exit code "
        f"{exit_code} with {captured!r}"
    )
    assert "unreadable.py" in captured.err, (
        f"stderr must name the path to fix, got {captured.err!r}"
    )
