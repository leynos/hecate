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
    Keeping the two apart is what leaves :func:`run_ruff` the only function
    here that touches the filesystem; a caller that wants both writes the
    composition itself, which is one line and says which half does what.

    Every shape this cannot read becomes one :class:`RuffPolicyError` rather
    than whichever exception the indexing happened to raise. A caller has no
    reason to know that a null location was a ``TypeError`` and a truncated
    report a ``JSONDecodeError``: both mean the report is not the report this
    reader understands, and neither may be read as "no diagnostics". The
    message names the diagnostic that could not be read where there is one, so
    a failure points at the entry rather than at the whole report, and the
    original exception is chained so the cause stays available.

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

    Raises
    ------
    RuffPolicyError
        If the report will not decode, is not a JSON array, or a diagnostic has
        no readable code and location. The message names the entry that could
        not be read where there is one.

    """
    try:
        diagnostics = json.loads(report)
    except json.JSONDecodeError as error:
        message = f"Ruff's report is not one this reader understands: {error}"
        raise RuffPolicyError(message) from error
    if not isinstance(diagnostics, list):
        message = (
            "Ruff's report is not one this reader understands: expected a "
            f"JSON array, got {type(diagnostics).__name__}"
        )
        raise RuffPolicyError(message)
    pairs: list[tuple[str, int]] = []
    for diagnostic in diagnostics:
        try:
            pairs.append(_code_and_row(diagnostic))
        except TypeError as error:
            message = (
                "Ruff reported a diagnostic with no readable code and "
                f"location: {diagnostic!r}"
            )
            raise RuffPolicyError(message) from error
    return pairs


def _code_and_row(diagnostic: object) -> tuple[str, int]:
    """Return one diagnostic's code and row, refusing a wrong-typed field.

    Indexing alone is not enough to read a diagnostic. A JSON report can carry
    ``null`` for ``code`` or a string where ``row`` should be, and both index
    successfully: the reader would hand a caller a pair whose members are not
    the types every caller compares, so a malformed report would read as "a
    code that is not in the expected set" rather than as a failure.

    Each field is checked where it is read rather than in one combined test.
    ``location`` has to be narrowed before it can be subscripted at all, and
    a single expression checking the code, the location and the row is longer
    than the project's boolean-expression limit.

    ``bool`` is excluded from ``int`` deliberately. ``True`` is an ``int`` to
    ``isinstance``, but a report that spells a row as a boolean is one Ruff
    does not emit, and accepting it would put ``True`` where a line number
    belongs.

    The raised ``TypeError`` carries the diagnostic, so the caller's single
    handler names the entry it could not read without this function having to
    build the same message twice.

    Parameters
    ----------
    diagnostic : object
        One entry of a decoded Ruff report.

    Returns
    -------
    tuple[str, int]
        The diagnostic's code and its one-based line.

    Raises
    ------
    TypeError
        If the entry is not a mapping, or its ``code``, ``location`` or
        ``row`` is missing or of the wrong type.

    """
    if not isinstance(diagnostic, dict):
        message = f"not a diagnostic object: {diagnostic!r}"
        raise TypeError(message)
    code = diagnostic.get("code")
    if not isinstance(code, str):
        message = f"diagnostic code is not a string: {diagnostic!r}"
        raise TypeError(message)
    location = diagnostic.get("location")
    if not isinstance(location, dict):
        message = f"diagnostic has no location object: {diagnostic!r}"
        raise TypeError(message)
    row = location.get("row")
    if not isinstance(row, int) or isinstance(row, bool):
        message = f"diagnostic row is not an integer line: {diagnostic!r}"
        raise TypeError(message)
    return code, row
