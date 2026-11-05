"""Contract: every suppression names its codes and says why.

Ruff 0.16 offers ``# ruff: ignore[...]`` beside ``# noqa``, and RUF105 asks
projects to prefer it. Adopting a spelling is only half a policy: a bare
``noqa`` suppresses everything on the line, and a suppression with no reason
is indistinguishable from one nobody thought about. Both are what this
contract refuses, and it refuses them by reading the modules rather than by
trusting the convention.

The files it reads are the ones the gate checks, obtained from Ruff itself, so
a directory added to the lint targets is covered without editing a list here.
The same rule is applied to literal text in ``test_reading``, which is what
keeps a passing repository scan from being vacuous.
"""

from __future__ import annotations

import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys

import pytest

from .reading import REPO_ROOT, RuffPolicyError, repository_files_present
from .suppressions import NOQA, Suppression, scan

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

#: The codes whose breadth would hide a subprocess risk. ``S404`` guards the
#: import, ``S603`` the call, ``S607`` the lookup of a partial path; a
#: file-level or block suppression of any of them would switch that guard off
#: for more than the line the author considered.
SECURITY_CODES = frozenset({"S404", "S603", "S607"})

#: The forms that span more than one line. A security code in either is what
#: the contract forbids, because the author's review covered one call site and
#: the comment covers a region.
BROAD_FORMS = frozenset({"file-ignore", "disable"})


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
        If Ruff cannot list them. A reader that returned ``()`` would leave
        every caller comparing empty sets and passing.

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
    root = f"{REPO_ROOT}/"
    return tuple(
        line.removeprefix(root)
        for line in completed.stdout.splitlines()
        if line.startswith(root)
    )


def checked_modules() -> tuple[str, ...]:
    """Return the Python files the lint gate checks, as relative paths.

    Returns
    -------
    tuple[str, ...]
        The checked modules, relative to the repository root, in Ruff's order.

    """
    return ruff_show_files(*LINT_TARGETS)


def violations(suppressions: tuple[Suppression, ...]) -> list[str]:
    """Return one message per suppression that breaks the convention.

    Parameters
    ----------
    suppressions : tuple[Suppression, ...]
        The suppressions read from one module.

    Returns
    -------
    list[str]
        A message for each broken rule, naming the line and the form. Several
        messages for one line are deliberate: a bare, unexplained ``noqa``
        breaks three rules, and a report naming only the first would leave the
        author to discover the rest on the next run.

    """
    found: list[str] = []
    for suppression in suppressions:
        where = f"line {suppression.line} ({suppression.form})"
        if suppression.form == NOQA:
            found.append(
                f"{where}: writes `noqa`, which every tool reads; use "
                "`ruff: ignore[...]` so the suppression is this project's "
                "decision rather than a generic one"
            )
        if not suppression.codes:
            found.append(
                f"{where}: names no codes, so it hides every diagnostic the "
                "line grows, including ones nobody has reviewed yet"
            )
        if not suppression.has_reason:
            found.append(f"{where}: has no rationale after a second `#`")
        if suppression.form in BROAD_FORMS and (
            broad := sorted(SECURITY_CODES.intersection(suppression.codes))
        ):
            found.append(
                f"{where}: suppresses {', '.join(broad)} for more than one "
                "line; put `ruff: ignore[...]` on each reviewed call site"
            )
    return found


def _scan_result() -> dict[str, list[str]]:
    """Return the convention messages for every checked module that has any."""
    return {
        path: messages
        for path, suppressions in scan(checked_modules(), read_module)
        if (messages := violations(suppressions))
    }


class TestRepositorySuppressions:
    """The suppressions in every module the gate checks."""

    def test_every_suppression_names_codes_and_a_reason(self) -> None:
        """A bare or unexplained suppression is policy nobody can review."""
        broken = _scan_result()
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

        Only ``.py`` files are compared. A bare ``ruff check`` also lists the
        ``pyproject.toml`` that configures it, which carries no suppression
        comments and which the gate never passes as a target.
        """
        scanned = set(checked_modules())
        unreachable = {
            path for path in ruff_show_files() if path.endswith(".py")
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
