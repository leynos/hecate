"""Behaviour: the migrated suppression still suppresses, and only its line.

A contract that reads comments cannot show that Ruff honours them. These
fixtures run the pinned binary over literal modules in ``tmp_path`` and assert
on the diagnostics it reports, so the syntax the repository migrated to is
proved rather than assumed. Each case carries its own negative control in the
same test: a fixture that never triggers would otherwise pass every
suppression claim.

S603 fires only when the argument vector is not made entirely of literal
strings, while S607 fires on a partial executable path, so a fixture
exercising both needs one variable in the vector.

The mode question has its own history, because Ruff changed the answer under
this repository. On 0.15.13 ``ruff: ignore[...]`` was preview-only: without
``--preview`` Ruff warned and left the diagnostic reported. From 0.17.3 the
syntax is honoured in stable mode and the warning is gone, so the cases below
pass with or without the flag. ``test_the_syntax_suppresses_without_preview``
pins the new premise, and would fail if a future release made the syntax
preview-only again. What did *not* change is that rule *names* are preview-only,
which is why the contract rejects them regardless.

A second question is what a migrated suppression does to the *other* tools that
read the same comment, and to the codes it does not name. Those cases live in
``test_suppression_shared_line``: they are a separate module because the two
together exceed the module-length cap, and each imports the runner from
``ruff_run`` rather than from the other test module.
"""

from __future__ import annotations

import json
from pathlib import Path

from .ruff_run import diagnostics as _diagnostics
from .ruff_run import run_ruff as _run_ruff

#: The codes the repository suppresses around subprocess calls, which is what
#: the migration rewrote and therefore what these fixtures exercise.
SECURITY = ("S603", "S607")

#: A vector with one variable element. S603 is a judgement about the vector
#: being untrusted, so an all-literal list is statically safe and draws S607
#: alone; the variable is what makes both diagnostics appear together.
_VECTOR = "name = 'make'\nsubprocess.run(['make', name], check=True)"

_SUPPRESS_S603 = "# ruff: ignore[S603]  # Fixed two-word vector."


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

    def test_the_syntax_suppresses_without_preview(self, tmp_path: Path) -> None:
        """The comment suppresses in stable mode, as it did under preview.

        This was the negative control while the syntax was a preview feature:
        on 0.15.13 it asserted that ``--preview`` was load-bearing. Ruff
        stabilized the syntax by 0.17.4, so the assertion inverted. Keeping it
        inverted is what records the change; deleting it would let a future
        release make the syntax preview-only again with nobody noticing.

        The rule *names* accepted inside the brackets are still preview-only,
        which is why the contract forbids them rather than relying on the mode.
        """
        suppressed = f"import subprocess\n{_VECTOR}  {_SUPPRESS_S603}\n"
        completed = _run_ruff(tmp_path, suppressed, ("S603",), preview=False)
        reported = [diagnostic["code"] for diagnostic in json.loads(completed.stdout)]
        assert reported == [], (
            "the suppression was ignored outside preview mode, so the syntax "
            "is preview-only again and the modes the fixtures run under no "
            f"longer match the repository's; diagnostics were {reported}"
        )
        assert "preview" not in completed.stderr.lower(), (
            "Ruff reported the stable-mode comment as preview-only, so the "
            f"premise above is wrong; stderr was {completed.stderr!r}"
        )

    def test_a_rule_name_in_the_brackets_is_still_preview_only(
        self, tmp_path: Path
    ) -> None:
        """The codes-versus-names distinction is the part Ruff did not stabilize.

        The contract rejects rule names in suppression comments. That is a
        policy choice, and this case records why it is also a necessary one:
        outside preview mode Ruff cannot resolve a name at all, so a suppression
        written with one would silently cover nothing in a stable-mode run.
        """
        named = (
            "import subprocess\n"
            f"{_VECTOR}  "
            "# ruff: ignore[subprocess-without-shell-equals-true]  # Named.\n"
        )
        reported = [
            diagnostic["code"]
            for diagnostic in json.loads(
                _run_ruff(tmp_path, named, ("S603",), preview=False).stdout
            )
        ]
        assert "S603" in reported, (
            "a rule name in the brackets suppressed S603 outside preview mode, "
            "so names are stable too and the contract's refusal to use them "
            "rests on a claim that no longer holds"
        )
