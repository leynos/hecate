"""Unit: reading a Ruff report is separate from producing one.

``run_ruff`` writes a fixture module and starts a process. Every contract that
asks what Ruff reported went straight through it, so nothing distinguished the
parse from the run: a parse that mishandled a real report would only show up as
a fixture that "suppressed" a code Ruff had in fact reported, or the reverse.

:func:`reported` is that parse, lifted out as a function of a string. These
cases hold it to hand-written reports, which is the only way to say what it
does with a shape a live run would have to be engineered to produce — an empty
report, several diagnostics, a diagnostic whose location is null.

The last case is the property the separation was for: the reader must not touch
the filesystem, so a caller can use it against a recorded report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .ruff_run import reported


class TestReportParsing:
    """A report in, ``(code, line)`` pairs out."""

    def test_an_empty_report_is_no_diagnostics(self) -> None:
        """A fixture that draws nothing is a result, not a malformed run."""
        assert reported("[]") == [], (
            "an empty report was not read as zero diagnostics, so the "
            "negative controls in the behaviour contracts could be reading a "
            "parse failure as a clean run"
        )

    def test_each_diagnostic_becomes_a_code_and_a_line(self) -> None:
        """The pairs must line up, in report order, with one-based rows."""
        report = json.dumps([
            {"code": "S404", "location": {"row": 1, "column": 1}},
            {"code": "F401", "location": {"row": 3, "column": 8}},
        ])
        assert reported(report) == [("S404", 1), ("F401", 3)], (
            "the reader did not map each diagnostic to its own code and row; "
            "a neighbour assertion built on this would compare one "
            "diagnostic's line against another's"
        )

    def test_two_diagnostics_on_one_line_are_both_kept(self) -> None:
        """Collapsing by code would hide an over-broad suppression."""
        report = json.dumps([
            {"code": "F401", "location": {"row": 2, "column": 1}},
            {"code": "F401", "location": {"row": 2, "column": 1}},
        ])
        assert len(reported(report)) == 2, (
            "two diagnostics sharing a code and a row were collapsed into "
            "one, so a count over the result would under-report"
        )

    def test_a_missing_location_is_an_error_not_a_silent_zero(self) -> None:
        """Ruff 0.16 can emit null locations; that must not read as line 1."""
        report = json.dumps([{"code": "S404", "location": None}])
        with pytest.raises(TypeError):
            reported(report)
        # ``None["row"]`` raises TypeError. Asserting the raise rather than a
        # sentinel is the point: a reader that substituted a row would report
        # a diagnostic at a line the author never wrote.


class TestNoFilesystemContact:
    """The reader is a function of text alone."""

    def test_reading_a_report_touches_no_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It must not create, read, or write anything to do its work."""
        monkeypatch.chdir(tmp_path)
        before = sorted(p.name for p in tmp_path.iterdir())
        assert reported('[{"code": "S404", "location": {"row": 7}}]') == [("S404", 7)]
        after = sorted(p.name for p in tmp_path.iterdir())
        assert after == before == [], (
            "reading a report touched the filesystem, so this is not the "
            f"read-only seam it is documented to be: {after}"
        )

    def test_a_truncated_report_raises_rather_than_returning_nothing(self) -> None:
        """A malformed report must not be read as a clean run.

        This is the failure that matters most in this function: every caller
        treats an empty list as "Ruff reported nothing", so a reader that
        swallowed a decode error would turn a broken run into a passing
        negative control.
        """
        with pytest.raises(json.JSONDecodeError):
            reported('[{"code": "S404", "location": {"row": 1')
