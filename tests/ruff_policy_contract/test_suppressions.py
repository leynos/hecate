"""Contract: every suppression names its codes and says why.

Ruff 0.16 offers ``# ruff: ignore[...]`` beside ``# noqa``, and RUF105 asks
projects to prefer it. Adopting a spelling is only half a policy: a bare
``noqa`` suppresses everything on the line, and a suppression with no reason
is indistinguishable from one nobody thought about. Both are what this
contract refuses, and it refuses them by reading the modules rather than by
trusting the convention.

The judgement itself is in ``convention.violations``, which reads no files.
This module applies it to the tree; the fixtures in ``test_reading_suppressions``
apply it to literal text, which is what keeps a passing repository scan from
being vacuous.

The files it reads are the ones the gate checks, obtained from Ruff itself, so
a directory added to the lint targets is covered without editing a list here.
"""

from __future__ import annotations

import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
import typing as typ
from pathlib import Path

import pytest

from .convention import violations
from .reading import REPO_ROOT, RuffPolicyError, repository_files_present
from .suppressions import scan

if typ.TYPE_CHECKING:
    import collections.abc as cabc

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "pyproject.toml or the sample module is not present in this working "
        "copy (for example inside a mutation-testing sandbox)"
    ),
)

#: The Python directories the gate checks. Deliberately not parsed out of the
#: Makefile: Ruff's file list already reflects ``extend-exclude`` and per-file
#: settings, which is the property the contract needs, and a Makefile parser
#: here would be a second implementation of variable expansion.
#:
#: That leaves the two lists able to drift, so
#: ``test_the_scan_covers_every_file_the_gate_checks`` compares the directories
#: named here against every module a bare ``ruff check`` reports, and fails on
#: any module this list leaves outside the scan.
LINT_TARGETS = ("hecate", "tests", "scripts")


def read_module(path: str) -> str:
    """Return one module's source, relative to the repository root.

    Parameters
    ----------
    path : str
        The module to read, as Ruff reported it: relative to the root and
        spelled with forward slashes.

    Returns
    -------
    str
        The module's text, decoded as UTF-8.

    """
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def ruff_show_files(*targets: str) -> tuple[str, ...]:
    """Return the modules Ruff lists for ``targets``, relative to the root.

    Ruff is asked for the files rather than a directory being walked: an
    excluded module is not linted, so a suppression in it is not policy the
    gate enforces and not something this contract should fail on. Paths are
    returned relative to :data:`REPO_ROOT` so callers can compare them against
    the paths they hand back to :func:`scan`.

    Parameters
    ----------
    *targets : str
        The paths to pass to Ruff. None means "no target", which leaves Ruff
        to apply its own configuration's include and exclude rules; that is a
        different question from "these directories", which is why the caller
        chooses rather than this helper defaulting to
        :data:`LINT_TARGETS`.

    Returns
    -------
    tuple[str, ...]
        The listed modules, relative to the repository root, in Ruff's order.

    Raises
    ------
    RuffPolicyError
        If Ruff cannot list them, or if it reports a path outside the
        repository root. A reader that silently dropped either would leave
        its callers comparing sets that quietly lost members, and passing.

    """
    try:
        completed = subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
            [sys.executable, "-m", "ruff", "check", "--show-files", *targets],
            capture_output=True,
            check=True,
            cwd=REPO_ROOT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        message = f"cannot list the files Ruff checks: {error}"
        raise RuffPolicyError(message) from error
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        try:
            paths.append(str(Path(line).relative_to(REPO_ROOT)))
        except ValueError as error:
            message = f"Ruff listed a path outside {REPO_ROOT}: {line}"
            raise RuffPolicyError(message) from error
    return tuple(paths)


def checked_modules() -> tuple[str, ...]:
    """Return the Python files the lint gate checks, as relative paths.

    Returns
    -------
    tuple[str, ...]
        The checked modules, relative to the repository root, in Ruff's order.

    """
    return ruff_show_files(*LINT_TARGETS)


def _scan_result(
    paths: cabc.Iterable[str], read: cabc.Callable[[str], str]
) -> dict[str, list[str]]:
    """Return the convention messages for each path that breaks one.

    The parameters are what make this drivable from a fixture as well as from
    the tree: the gate calls it with :func:`checked_modules` and
    :func:`read_module`, and a case here passes literal sources and their own
    lookup. Both therefore exercise this one scan-and-filter, so a case cannot
    pass against a copy of it.

    A path whose suppressions all follow the convention is left out rather than
    mapped to an empty list, so a caller can assert against the set of paths
    the scan had something to say about.

    Parameters
    ----------
    paths : cabc.Iterable[str]
        The paths to scan, as a reviewer should see them in the report.
    read : cabc.Callable[[str], str]
        Returns the source text for one path.

    Returns
    -------
    dict[str, list[str]]
        One entry per path with at least one message, in scan order.

    """
    return {
        path: messages
        for path, found in scan(paths, read)
        if (messages := violations(found))
    }


class TestRepositorySuppressions:
    """The suppressions in every module the gate checks."""

    def test_every_suppression_names_codes_and_a_reason(self) -> None:
        """A bare or unexplained suppression is policy nobody can review."""
        broken = _scan_result(checked_modules(), read_module)
        assert not broken, (
            "these suppressions break the house convention: "
            f"{broken}. Write `# ruff: ignore[CODE]  # why this is safe` on "
            "the line Ruff reports the diagnostic on"
        )

    def test_the_scan_covers_every_file_the_gate_checks(self) -> None:
        """A directory added to the gate must not slip past the convention.

        ``LINT_TARGETS`` is a hand-written list beside a Makefile that owns
        the real one, so the two can drift: a new directory added to
        ``PYTHON_TARGETS`` would be linted by Ruff and never read here, and
        this suite would still pass. Ruff's own file list is what the gate
        acts on, so it is the set the reader must cover.

        Python modules and stubs are compared, because Ruff lints both and a
        stub can carry a suppression comment as readily as a module. The
        ``pyproject.toml`` that a bare ``ruff check`` also lists is excluded:
        it carries no comments at all, and the gate never passes it as a
        target.
        """
        scanned = set(checked_modules())
        unreachable = {
            path for path in ruff_show_files() if Path(path).suffix in {".py", ".pyi"}
        } - scanned
        assert not unreachable, (
            "Ruff checks these modules but the suppression contract never "
            f"reads them: {sorted(unreachable)}. Add their directory to "
            "LINT_TARGETS, or narrow the Makefile's Ruff targets so the two "
            "describe the same set"
        )

    def test_the_scan_actually_reaches_suppression_comments(self) -> None:
        """A reader that found nothing would pass the contract vacuously."""
        total = sum(
            len(suppressions)
            for _, suppressions in scan(checked_modules(), read_module)
        )
        assert total, (
            "no suppression was found in any checked module, so the "
            "convention above was never exercised; check that the reader "
            "still matches the spelling the project writes"
        )


class TestScanReport:
    """A scan must name the offending path, not only that something is wrong."""

    def test_an_invalid_suppression_is_reported_against_its_path(self) -> None:
        """The report a reviewer reads must say which file and which line.

        ``_scan_result`` is the whole gate's output, and until now nothing
        asserted its shape: a reader that dropped the path, or that reported
        every file whether or not it broke the convention, would have satisfied
        every case above. This drives the same reader over literal sources and
        checks the two halves a person needs — the path, and a message naming
        the line.
        """
        sources = {
            "bad.py": "x = 1  # noqa\n",
            "good.py": "y = 2  # ruff: ignore[S404]  # Why this is safe.\n",
        }
        reported = _scan_result(sources, sources.__getitem__)
        assert set(reported) == {"bad.py"}, (
            "the scan reported on the wrong set of paths; a clean module was "
            f"named or the broken one was not: {sorted(reported)}"
        )
        assert any("line 1" in message for message in reported["bad.py"]), (
            "the report for the broken module does not name its line, so a "
            f"reviewer cannot find it: {reported['bad.py']}"
        )

    def test_a_valid_suppression_produces_no_report(self) -> None:
        """The negative control: the same scan must clear a clean module."""
        sources = {"good.py": "y = 2  # ruff: ignore[S404]  # Why this is safe.\n"}
        reported = _scan_result(sources, sources.__getitem__)
        assert reported == {}, (
            "a module whose only suppression names a code and a reason was "
            f"reported against: {reported}"
        )
