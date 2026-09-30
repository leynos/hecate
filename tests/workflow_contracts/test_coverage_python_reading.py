"""Contract reader: how the coverage contract reads its inputs and refuses bad ones.

Companion to ``test_coverage_python_version.py``, which applies the resolver to
this repository's lanes. These cases exercise the reading boundary alone: the
``.python-version`` parser, the optional-file read that only treats a missing
file as absent, and the strict loader that refuses a wrongly shaped workflow.
"""

from __future__ import annotations

import typing as typ

import pytest

from .coverage_python_sources import (
    coverage_calls,
    python_version_entry,
    read_text_if_present,
)
from .loading import WorkflowReadingError

if typ.TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, ""),
        ("", ""),
        ("3.13\n", "3.13"),
        ("# pinned\n\n  3.13  \n3.12\n", "3.13"),
        ("# comments only\n", ""),
    ],
    ids=["absent", "empty", "one-entry", "first-entry-after-comments", "comments-only"],
)
def test_the_python_version_entry_is_the_first_non_comment_line(
    text: str | None, expected: str
) -> None:
    """Parsing is pure: the first non-comment entry, or nothing."""
    assert python_version_entry(text) == expected, f"{text!r} should read {expected!r}"


def test_a_python_version_file_is_read_from_the_tree(tmp_path: Path) -> None:
    """A real ``.python-version`` feeds the parser; a missing one reads as absent."""
    present = tmp_path / ".python-version"
    present.write_text("# pinned\n3.12\n", encoding="utf-8")

    assert python_version_entry(read_text_if_present(present)) == "3.12", (
        "a present file is read and parsed"
    )
    assert read_text_if_present(tmp_path / "missing" / ".python-version") is None, (
        "a missing file reads as absent, not as empty text"
    )


@pytest.mark.parametrize(
    ("kind", "cause"),
    [("undecodable", UnicodeDecodeError), ("directory", OSError)],
    ids=["undecodable", "directory"],
)
def test_an_optional_file_that_cannot_be_read_fails_loudly(
    tmp_path: Path, kind: str, cause: type[Exception]
) -> None:
    """Only absence reads as absent; a directory or undecodable file raises.

    The typed error names the path and keeps the original failure as its cause.
    """
    path = tmp_path / kind
    if kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"\xff\xfe")

    with pytest.raises(WorkflowReadingError, match=kind) as raised:
        read_text_if_present(path)

    assert isinstance(raised.value.__cause__, cause), (
        f"{kind} should chain {cause.__name__}, got {raised.value.__cause__!r}"
    )


@pytest.mark.parametrize(
    "workflow",
    ["jobs: scalar\n", "jobs:\n  cov: scalar\n", "jobs:\n  cov: [x]\n"],
    ids=["scalar-jobs", "scalar-job", "list-job"],
)
def test_a_wrongly_shaped_jobs_level_reads_as_no_calls(workflow: str) -> None:
    """The traversal treats a wrongly shaped jobs mapping or job as empty."""
    assert coverage_calls(workflow) == [], f"{workflow!r} should hold no coverage calls"


@pytest.mark.parametrize(
    "workflow",
    [
        "",
        "- a list\n",
        "jobs:\n  cov:\n    steps: []\n    steps: []\n",
        "jobs:\n  cov:\n    steps:\n      - with: {a: 1}\n        with: {a: 2}\n",
    ],
    ids=["empty", "list-top-level", "duplicate-steps", "duplicate-with"],
)
def test_a_workflow_the_strict_loader_refuses_is_refused(workflow: str) -> None:
    """A duplicate key or a non-mapping document cannot hide a call or input."""
    with pytest.raises(WorkflowReadingError):
        coverage_calls(workflow)
