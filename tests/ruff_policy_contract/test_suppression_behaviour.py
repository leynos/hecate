"""Behaviour: the migrated suppression still suppresses, and only its line.

A contract that reads comments cannot show that Ruff honours them. These
fixtures run the pinned binary over literal modules in ``tmp_path`` and assert
on the diagnostics it reports, so the syntax the repository migrated to is
proved rather than assumed. Each case carries its own negative control in the
same test: a fixture that never triggers would otherwise pass every
suppression claim.

Two measured facts about Ruff shape every case. ``ruff: ignore[...]`` is a
preview feature, so Ruff warns and reports the diagnostic unless the run
enables preview mode; the project does, and these fixtures do for the same
reason. And S603 fires only when the argument vector is not made entirely of
literal strings, while S607 fires on a partial executable path, so a fixture
exercising both needs one variable in the vector.
"""

from __future__ import annotations

import json
import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
from pathlib import Path

from .reading import RuffPolicyError

#: The codes the repository suppresses around subprocess calls, which is what
#: the migration rewrote and therefore what these fixtures exercise.
SECURITY = ("S603", "S607")

#: A vector with one variable element. S603 is a judgement about the vector
#: being untrusted, so an all-literal list is statically safe and draws S607
#: alone; the variable is what makes both diagnostics appear together.
_VECTOR = "name = 'make'\nsubprocess.run(['make', name], check=True)"

_SUPPRESS_S603 = "# ruff: ignore[S603]  # Fixed two-word vector."


def _run_ruff(
    tmp_path: Path,
    source: str,
    codes: tuple[str, ...],
    *,
    preview: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Check ``source`` in ``tmp_path`` and return Ruff's completed run.

    The module is checked in isolation so the repository's own configuration
    cannot change the outcome: what is under test is the suppression syntax,
    and a fixture inheriting the project's selectors would be measuring those
    as well. Preview mode is enabled explicitly for the same reason in the
    other direction — it is what the project's configuration sets, and without
    it the syntax under test is inert.

    Parameters
    ----------
    tmp_path : Path
        Where to write the fixture module.
    source : str
        The module to check.
    codes : tuple[str, ...]
        The rule codes to select. Anything outside this set is ignored, so an
        unrelated diagnostic cannot be mistaken for the one under test.
    preview : bool
        Whether to run Ruff with preview mode. Callers turn it off only to
        show that the syntax depends on it.

    Returns
    -------
    subprocess.CompletedProcess[str]
        The finished run, with Ruff's JSON report on standard output.

    Raises
    ------
    RuffPolicyError
        If Ruff could not check the fixture. A fixture error must not read as
        an absent diagnostic, which is what every assertion here concludes on.

    """
    (tmp_path / "fixture.py").write_text(source, encoding="utf-8")
    arguments = [sys.executable, "-m", "ruff", "check", "--isolated"]
    if preview:
        arguments.append("--preview")
    arguments += [f"--select={code}" for code in codes]
    arguments += ["--output-format", "json", "fixture.py"]
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


def _diagnostics(tmp_path: Path, source: str, codes: tuple[str, ...]) -> list[str]:
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
    completed = _run_ruff(tmp_path, source, codes)
    return [diagnostic["code"] for diagnostic in json.loads(completed.stdout)]


class TestSuppressionScope:
    """What a migrated suppression does and does not cover."""

    def test_a_suppression_silences_only_the_codes_it_names(
        self, tmp_path: Path
    ) -> None:
        """A neighbouring code on the same line must stay visible."""
        unsuppressed = f"import subprocess\n{_VECTOR}\n"
        reported = _diagnostics(tmp_path, unsuppressed, SECURITY)
        assert set(SECURITY) <= set(reported), (
            "the fixture does not trigger both security codes, so the "
            "assertion below would pass whether or not the suppression "
            f"did anything; it reported {reported}"
        )

        suppressed = f"import subprocess\n{_VECTOR}  {_SUPPRESS_S603}\n"
        reported = _diagnostics(tmp_path, suppressed, SECURITY)
        assert "S603" not in reported, (
            "a suppression naming S603 did not silence it, so the syntax the "
            "migration relies on does not do what the contract assumes"
        )
        assert "S607" in reported, (
            "the neighbouring S607 was silenced by a comment naming only "
            "S603, so a suppression is broader than the code written on it"
        )

    def test_removing_the_comment_restores_the_diagnostic(self, tmp_path: Path) -> None:
        """The suppression, not the fixture, is what keeps the codes quiet."""
        unsuppressed = f"import subprocess\n{_VECTOR}\n"
        assert set(_diagnostics(tmp_path, unsuppressed, SECURITY)) == set(SECURITY), (
            "the call does not trigger both selected diagnostics, so the "
            "assertion below would pass whether or not the suppression did "
            "anything"
        )

        both = "# ruff: ignore[S603, S607]  # Fixed two-word vector."
        suppressed = f"import subprocess\n{_VECTOR}  {both}\n"
        assert not _diagnostics(tmp_path, suppressed, SECURITY), (
            "a suppression naming both codes did not silence the call's "
            "diagnostics, and that is the form the migration relies on"
        )

    def test_a_call_line_suppression_does_not_reach_an_argument_line(
        self, tmp_path: Path
    ) -> None:
        """Each code is reported on its own line, and needs its own comment."""
        multi_line = (
            "import subprocess\n"
            "name = 'make'\n"
            "subprocess.run(\n"
            "    ['make', name],\n"
            "    check=True,\n"
            ")\n"
        )
        assert set(_diagnostics(tmp_path, multi_line, SECURITY)) == set(SECURITY), (
            "the multi-line call does not trigger both codes, so the scope "
            "assertions below would pass vacuously"
        )

        call_line_only = multi_line.replace(
            "subprocess.run(\n",
            "subprocess.run(  # ruff: ignore[S603]  # Fixed two-word vector.\n",
        )
        reported = _diagnostics(tmp_path, call_line_only, SECURITY)
        assert "S603" not in reported, (
            "a suppression on the call line did not silence S603, which "
            "Ruff reports there"
        )
        assert "S607" in reported, (
            "a suppression on the call line also covered the argument line, "
            "so S607 reaches further than where Ruff reports it"
        )

        per_argument = call_line_only.replace(
            "    ['make', name],\n",
            "    ['make', name],  # ruff: ignore[S607]  # make comes from PATH.\n",
        )
        assert not _diagnostics(tmp_path, per_argument, SECURITY), (
            "a suppression on the argument line did not silence S607, which "
            "is where Ruff reports it for a multi-line call"
        )

    def test_the_syntax_is_inert_without_preview(self, tmp_path: Path) -> None:
        """The comment only suppresses when preview mode is on.

        This is the negative control for the helper: if ``--preview`` changed
        nothing, the tests above would still pass, and the project's reliance
        on a preview feature would be untested.
        """
        suppressed = f"import subprocess\n{_VECTOR}  {_SUPPRESS_S603}\n"
        completed = _run_ruff(tmp_path, suppressed, ("S603",), preview=False)
        reported = [diagnostic["code"] for diagnostic in json.loads(completed.stdout)]
        assert reported == ["S603"], (
            "the suppression was honoured outside preview mode, so the "
            "fixtures above prove nothing about the mode the project enables"
        )
        assert "preview" in completed.stderr.lower(), (
            "Ruff explained the inactive comment no further; the fixture "
            f"still reported the diagnostic, but this message was {completed.stderr!r}"
        )
