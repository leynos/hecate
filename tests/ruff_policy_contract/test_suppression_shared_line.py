"""Behaviour: a migrated suppression beside a code it does not name, or a pragma.

The migration rewrote comments that were not alone on their line. Two things
could share a line with a suppression, and both are tested here.

The first is present in the tree and is the case the migration actually met.
``import subprocess`` draws ``S404``, the security judgement about importing a
process-spawning module, and ``F401``, the ordinary "imported but unused"
finding. They are reported on the same line, so an ``import`` is the natural
place to show that naming one code leaves its neighbour visible.

The second is not present at the base and is a compatibility case rather than a
migrated one. The tree carries exactly one ``# pragma: no cover``, on a line
with no suppression, so no comment here was ever rewritten to carry both. The
fixture exists because a line that a coverage run skips carries that pragma,
and the policy comment has to be able to share it without displacing it if the
two ever do meet. A pragma on its own is the negative control — it is not a
suppression, and must not act as one.

What the cases here assert is narrower than a coverage measurement, and the
narrowing is deliberate rather than a gap left open. ``coverage`` is not a
project dependency, and adding it would edit ``pyproject.toml`` and
``uv.lock``, which the pending grouped Dependabot update also edits — the
contract test would collide with the very change whose validation depends on
this branch. So the suite asserts the two facts it can assert without the
tool: the pragma survives verbatim in the migrated comment, and Ruff still
honours its own directive beside it.

The coverage half was measured out of band instead, with the real tool, and
the result is recorded in the ExecPlan's Milestone 3 evidence: across both
directive orders and a pragma-only control, ``analysis2`` reports the commented
line as excluded in all three, while the no-comment control reports that same
line as missing. That is the four-way matrix of the same comment variants these
cases build — not the same fixtures verbatim, because the driver places each
import inside a function it never calls so the line genuinely does not execute,
whereas the cases here import at module top level. Reproducing it needs only
``uv tool run --from coverage``; nothing in the repository changes.

This module is separate from ``test_suppression_behaviour`` because the two
together exceed the module-length cap. It imports the runner from
``ruff_run``, the non-test seam, rather than from the sibling test module.
"""

from __future__ import annotations

from pathlib import Path

from .ruff_run import reported as read_report
from .ruff_run import run_ruff

#: The line both codes are reported on. S404 is the security judgement about
#: importing a process-spawning module; F401 is the ordinary "imported but
#: unused" finding, which has nothing to do with the suppression policy.
_IMPORT = "import subprocess"

_IMPORT_CODES = ("S404", "F401")

#: The pragma a coverage reader looks for, written the way the repository's one
#: existing pragma is. A suppressed line has to be able to carry it too.
_PRAGMA = "# pragma: no cover"


class TestTwoToolsOneLine:
    """A migrated suppression beside a code it does not name, or a pragma.

    A migration that only worked for a comment owning the whole line would
    have broken both of these positions.
    """

    def test_an_import_reports_both_of_its_codes(self, tmp_path: Path) -> None:
        """The negative control: nothing suppressed, so both codes appear."""
        reported = read_report(run_ruff(tmp_path, f"{_IMPORT}\n", _IMPORT_CODES).stdout)
        assert {code for code, _ in reported} == set(_IMPORT_CODES), (
            "the fixture does not draw both of the codes the assertions "
            "below are about, so every suppression claim that follows would "
            f"pass vacuously; it reported {reported}"
        )

    def test_naming_one_code_leaves_the_other_on_the_same_line(
        self, tmp_path: Path
    ) -> None:
        """Suppressing S404 must not take F401 with it."""
        suppressed = f"{_IMPORT}  # ruff: ignore[S404]  # Runs the pinned Ruff.\n"
        reported = read_report(run_ruff(tmp_path, suppressed, _IMPORT_CODES).stdout)
        assert ("S404", 1) not in reported, (
            "a suppression naming S404 did not silence it on an import line, "
            "so the migration does not work in the position it was applied"
        )
        assert ("F401", 1) in reported, (
            "suppressing S404 also hid F401, an unrelated code Ruff reports "
            "on the same line, so a suppression is broader than the codes "
            f"written on it; it reported {reported}"
        )

    def test_a_neighbouring_import_stays_checked(self, tmp_path: Path) -> None:
        """A trailing suppression covers its own line and no other."""
        source = (
            f"{_IMPORT}  # ruff: ignore[S404]  # Runs the pinned Ruff.\nimport os\n"
        )
        reported = read_report(run_ruff(tmp_path, source, _IMPORT_CODES).stdout)
        assert ("S404", 1) not in reported, (
            "the suppressed first import line still drew S404"
        )
        assert ("F401", 2) in reported, (
            "the unsuppressed import on the next line was not checked, so a "
            "trailing suppression reaches beyond its own line; it reported "
            f"{reported}"
        )

    def test_a_pragma_alone_leaves_the_security_code_reported(
        self, tmp_path: Path
    ) -> None:
        """A coverage pragma is not a suppression, and must not act as one."""
        source = f"{_IMPORT}  {_PRAGMA}\n"
        reported = read_report(run_ruff(tmp_path, source, _IMPORT_CODES).stdout)
        assert ("S404", 1) in reported, (
            "a coverage pragma silenced S404, so Ruff read the pragma as a "
            "suppression; the migration could then be replaced by a pragma, "
            f"which is not a reviewed security decision; it reported {reported}"
        )

    def test_a_migrated_suppression_shares_a_line_with_a_coverage_pragma(
        self, tmp_path: Path
    ) -> None:
        """One comment must carry both directives without losing either.

        The order written here is the suppressed directive first, its
        rationale second, and the pragma last. That is the shape the migration
        produces when a previously ``noqa``-carrying line was also skipped by
        coverage: the policy comment stays first, and the pragma is appended
        rather than replacing anything.

        The assertions below are the two this module can make without
        ``coverage`` installed — the pragma survives textually, and Ruff still
        honours its own directive beside it. The coverage half of this same
        four-way matrix was measured out of band and is recorded in the
        ExecPlan's Milestone 3 evidence; see the module docstring.
        """
        source = f"{_IMPORT}  # ruff: ignore[S404]  # Runs it.  {_PRAGMA}\n"
        text = source.split("#", 1)[1]
        assert "ruff: ignore[S404]" in text, (
            "the shared comment lost its directive, so nothing would suppress "
            "S404 and the assertion below would be measuring a plain pragma"
        )
        assert "pragma: no cover" in text, (
            "the shared comment lost the coverage pragma, so the migration "
            "displaced the other tool's directive"
        )

        reported = read_report(run_ruff(tmp_path, source, _IMPORT_CODES).stdout)
        assert ("S404", 1) not in reported, (
            "the directive stopped suppressing once a pragma shared its line, "
            "so the pragma displaced Ruff's own reader of the comment"
        )
        assert ("F401", 1) in reported, (
            "sharing the line with a pragma widened the suppression beyond "
            f"the code it names; it reported {reported}"
        )

    def test_the_pragma_survives_the_directive_being_read_first(
        self, tmp_path: Path
    ) -> None:
        """Writing the pragma before the directive is equally acceptable.

        Both directives are matched as substrings of the comment, so the order
        is a style question rather than a correctness one. Recording that here
        keeps the contract from silently requiring one order, which would make
        a later reformat look like a behaviour change.

        As above, this records that Ruff still suppresses and that the pragma
        text is still present; it does not measure coverage.
        """
        source = f"{_IMPORT}  {_PRAGMA}  # ruff: ignore[S404]  # Runs it.\n"
        reported = read_report(run_ruff(tmp_path, source, _IMPORT_CODES).stdout)
        assert ("S404", 1) not in reported, (
            "the directive stopped suppressing when the pragma came first, "
            "so the position of the pragma inside the comment decides whether "
            "Ruff still finds its own directive"
        )
        assert ("F401", 1) in reported, (
            f"the suppression widened past the code it names; it reported {reported}"
        )
