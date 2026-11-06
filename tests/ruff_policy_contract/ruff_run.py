"""Run the pinned Ruff over a literal fixture module and read its report.

A contract that reads comments cannot show that Ruff honours them, so the
behaviour contracts write a module into a temporary directory and check it
with the real binary. Several of those contracts now need that same runner,
and the alternative — one test module importing another — would drag the
imported module's ``pytestmark`` and fixture assumptions along with the
function. This module is the seam: it depends on nothing in the test tree, so
whichever contract imports it gets the runner and nothing else.

The module is checked in isolation. Inheriting the repository's own selectors
would make each fixture measure the project's configuration as well as the
syntax under test, and the point of these fixtures is to be about one
behaviour at a time. Callers name the codes they want, so an unrelated
diagnostic cannot be mistaken for the one under test.

Running and reading are separate functions for a reason. ``run_ruff`` is the
one function that writes a file and starts a process; :func:`reported` is a
pure parse of the JSON that comes back. A caller that wants to show what Ruff
reported for a recorded run can call the reader alone, and the unit tests here
hold it to a hand-written report without touching the filesystem.
"""

from __future__ import annotations

import json
import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
import typing as typ

from .reading import RuffPolicyError

if typ.TYPE_CHECKING:
    from pathlib import Path

#: The fixture's file name. One name keeps the written module recognizable in
#: a failing report, and nothing here depends on the module being importable.
FIXTURE_NAME = "fixture.py"


def run_ruff(
    tmp_path: Path,
    source: str,
    codes: tuple[str, ...],
    *,
    preview: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Check ``source`` in ``tmp_path`` and return Ruff's completed run.

    Parameters
    ----------
    tmp_path : Path
        Where to write the fixture module.
    source : str
        The module to check.
    codes : tuple[str, ...]
        The rule codes to select. Anything outside this set is ignored.
    preview : bool
        Whether to run Ruff with preview mode. Callers turn it off only to
        show that a syntax depends on it.

    Returns
    -------
    subprocess.CompletedProcess[str]
        The finished run, with Ruff's JSON report on standard output.

    Raises
    ------
    RuffPolicyError
        If Ruff could not check the fixture. A fixture error must not read as
        an absent diagnostic, which is what every caller here concludes on.

    """
    (tmp_path / FIXTURE_NAME).write_text(source, encoding="utf-8")
    arguments = [sys.executable, "-m", "ruff", "check", "--isolated"]
    if preview:
        arguments.append("--preview")
    arguments += [f"--select={code}" for code in codes]
    arguments += ["--output-format", "json", FIXTURE_NAME]
    # The interpreter is named explicitly so the fixture uses the same Ruff
    # the gate runs, rather than whatever is first on PATH.
    completed = subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
        arguments,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        message = f"ruff failed on the fixture: {completed.stderr}"
        raise RuffPolicyError(message)
    return completed


def reported(report: str) -> list[tuple[str, int]]:
    """Return each diagnostic in a Ruff JSON report as a code and a line.

    This is a reader of text, not a runner: it starts no process and writes no
    file, so a caller can hold it to its parse of a report recorded earlier.
    Keeping the two apart is what lets ``diagnostics_*`` below be the only
    functions here that touch the filesystem.

    Parameters
    ----------
    report : str
        Ruff's standard output from ``--output-format json``.

    Returns
    -------
    list[tuple[str, int]]
        One ``(code, one-based line)`` pair per diagnostic, in report order.
        An empty report is an empty list rather than an error: a fixture that
        draws no diagnostic is a result, not a malformed run.

    """
    return [
        (diagnostic["code"], diagnostic["location"]["row"])
        for diagnostic in json.loads(report)
    ]


def diagnostics_with_lines(
    tmp_path: Path, source: str, codes: tuple[str, ...]
) -> list[tuple[str, int]]:
    """Write ``source`` to a fixture module, check it, and read the report.

    A case that asks whether a *neighbouring* line is still checked needs the
    line, not only the code: two occurrences of one code are one entry each,
    and a set of codes would collapse them and hide an over-broad suppression
    that also silenced the neighbour.

    Parameters
    ----------
    tmp_path : Path
        Where to write the fixture module.
    source : str
        The module to check.
    codes : tuple[str, ...]
        The rule codes to select.

    Returns
    -------
    list[tuple[str, int]]
        One ``(code, line)`` pair per diagnostic, in Ruff's report order.

    """
    return reported(run_ruff(tmp_path, source, codes).stdout)


def diagnostics(tmp_path: Path, source: str, codes: tuple[str, ...]) -> list[str]:
    """Return the codes Ruff reports for ``source``, restricted to ``codes``.

    Parameters
    ----------
    tmp_path : Path
        Where to write the fixture module.
    source : str
        The module to check.
    codes : tuple[str, ...]
        The rule codes to select.

    Returns
    -------
    list[str]
        One entry per diagnostic, in Ruff's report order.

    """
    return [code for code, _ in diagnostics_with_lines(tmp_path, source, codes)]
