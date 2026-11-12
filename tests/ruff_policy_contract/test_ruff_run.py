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

from .reading import RuffPolicyError
from .ruff_run import reported


class TestReportParsing:
    """A report in, ``(code, line)`` pairs out."""

    def test_an_empty_report_is_no_diagnostics(self) -> None:
        """A fixture that draws nothing is a result, not a malformed run."""
        assert not reported("[]"), (
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
        """Ruff can emit a null location; that must not read as line 1.

        A reader that substituted a row would report a diagnostic at a line
        the author never wrote, so the case asserts a rejection rather than a
        sentinel, and names no inner exception: which one the failed index
        happened to raise is an implementation detail, while
        :class:`RuffPolicyError` is the contract every caller here handles.
        """
        report = json.dumps([{"code": "S404", "location": None}])
        with pytest.raises(RuffPolicyError) as raised:
            reported(report)
        assert "S404" in str(raised.value) or "location" in str(raised.value), (
            "the rejection does not mention what it could not read, so a "
            f"reader debugging a real report learns nothing: {raised.value!r}"
        )


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
        with pytest.raises(RuffPolicyError) as raised:
            reported('[{"code": "S404", "location": {"row": 1')
        assert "reader understands" in str(raised.value), (
            "a truncated report should surface as a policy error saying the "
            f"report was not readable: {raised.value!r}"
        )


class TestShapesThatDecodeButAreNotReports:
    """Valid JSON that is not a report must not be iterated as one.

    JSON decoding succeeds on a surprising amount of text that says nothing
    about diagnostics. Each of these is a report shape Ruff does not emit, so
    the reader has to refuse it; what it must not do is fall through to an
    exception the caller does not handle, or — worse — return a pair whose
    fields are not the types every caller indexes and compares.
    """

    @pytest.mark.parametrize(
        ("report", "description"),
        [
            ('{"code": "S404"}', "an object whose keys would iterate as codes"),
            ("null", "a JSON null, which is not iterable at all"),
            ("7", "a number, which is not iterable at all"),
        ],
    )
    def test_a_report_that_is_not_a_list_is_refused(
        self, report: str, description: str
    ) -> None:
        """A non-list decodes cleanly and then cannot be a diagnostic list.

        An object is the trap: iterating it yields its keys, which are
        strings, so the old reader reported a "diagnostic" it had invented
        rather than a report it could not read. A null or a number raises out
        of the loop entirely, escaping the ``RuffPolicyError`` contract the
        docstring states.
        """
        with pytest.raises(RuffPolicyError) as raised:
            reported(report)
        assert "expected a JSON array" in str(raised.value), (
            f"{description} was not refused as a report shape, so a caller "
            f"sees an error about a diagnostic that does not exist: "
            f"{raised.value!r}"
        )

    @pytest.mark.parametrize(
        ("diagnostic", "description"),
        [
            ('{"code": null, "location": {"row": 3}}', "a null code"),
            ('{"code": 404, "location": {"row": 3}}', "a numeric code"),
            ('{"code": "S404", "location": {"row": "3"}}', "a string row"),
            ('{"code": "S404", "location": {"row": 3.5}}', "a fractional row"),
            ('{"code": "S404", "location": {"row": true}}', "a boolean row"),
        ],
    )
    def test_a_diagnostic_with_unreadable_fields_is_refused(
        self, diagnostic: str, description: str
    ) -> None:
        """A wrong-typed field must fail here, not in a caller's comparison.

        Every caller compares codes against a set and rows against numbers, so
        a ``None`` code does not raise — it silently reads as "a code that is
        not in the expected set", which turns a malformed report into a
        passing negative control. ``isinstance`` is what rejects these, not
        indexing: each of them indexes fine.
        """
        with pytest.raises(RuffPolicyError) as raised:
            reported(f"[{diagnostic}]")
        assert "readable code and location" in str(raised.value), (
            f"{description} passed through as a diagnostic, so callers "
            f"compare a value of the wrong type: {raised.value!r}"
        )
