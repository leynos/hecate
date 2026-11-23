"""Contract: what a suppression's spelling has to look like for Ruff to read it.

Ruff matches the ``ruff:`` prefix, the directive name and the rule codes
case-sensitively. The measurement was taken on 0.15.13 and re-checked on the
pinned 0.17.3, over a call that trips S607: the canonical
``ruff: ignore[S607]`` suppresses the diagnostic, while a wrong-case prefix, a
wrong-case name or a lower-case code each leave it reported. That makes a
wrongly-cased comment the worst kind of suppression — it reads as reviewed
policy and does nothing.

Ruff itself reports only one of these: a wrong-case directive name draws
RUF103 ("unknown ruff directive"). A wrong-case prefix and a wrong-case code
draw no diagnostic at all, so nothing but this contract would notice them.

``noqa`` is different in one respect only: Ruff reads the word itself in any
casing, but its code list is case-sensitive like the other spelling's.
"""

from __future__ import annotations

import pytest

from .reporting import reported
from .suppressions import NOQA, suppressions_in


class TestMisCasedRuffDirectives:
    """Spellings that look like policy and are not."""

    def test_a_wrong_case_prefix_is_reported(self) -> None:
        """``# RUFF:`` draws no RUF diagnostic, so only this contract sees it."""
        messages = reported("x = 1  # RUFF: ignore[E501]  # Reviewed.\n")
        assert any("case" in message for message in messages), (
            "an upper-case prefix, which Ruff matches nowhere, passed the "
            "contract silently"
        )

    def test_a_wrong_case_directive_name_is_reported(self) -> None:
        """Ruff calls this RUF103; the contract must report it too."""
        messages = reported("x = 1  # ruff: IGNORE[E501]  # Reviewed.\n")
        assert any("case" in message for message in messages), (
            "an upper-case directive name passed the contract silently"
        )

    def test_a_lower_case_code_is_reported(self) -> None:
        """A lower-case code is a real code Ruff will not match."""
        messages = reported("x = 1  # ruff: ignore[e501]  # Reviewed.\n")
        assert any("case" in message for message in messages), (
            "a lower-case code, which Ruff does not match, passed the contract"
        )

    @pytest.mark.parametrize(
        "comment",
        [
            "# RUFF: ignore[E501]  # Reviewed.",
            "# Ruff: Ignore[E501]  # Reviewed.",
            "# ruff: IGNORE[E501]  # Reviewed.",
        ],
        ids=["upper-prefix", "title-case", "upper-name"],
    )
    def test_a_mis_cased_directive_is_read_at_all(self, comment: str) -> None:
        """Reading it is what lets the gate report it.

        A reader that treated these as prose would leave a comment that looks
        like policy, and suppresses nothing, entirely unremarked. The report is
        asserted separately above; this asserts the reader got far enough to
        make one possible.
        """
        (suppression,) = suppressions_in(f"x = 1  {comment}\n")
        assert suppression.form == "ignore", (
            f"{comment!r} was not read, so the gate cannot report it"
        )

    def test_the_canonical_spelling_is_recorded_as_canonical(self) -> None:
        """The case rule must not fire on the spelling the project writes."""
        (suppression,) = suppressions_in("x = 1  # ruff: ignore[S603]  # Reviewed.\n")
        assert suppression.records_canonical_case, (
            "the canonical spelling was reported as wrongly-cased, so the rule "
            "would fail on every suppression in the tree"
        )
        assert not reported("x = 1  # ruff: ignore[S603]  # Reviewed.\n"), (
            "a canonical, explained suppression drew a report"
        )

    def test_the_record_keeps_a_normalized_form_beside_the_written_one(self) -> None:
        """A report should read the same whichever case the author typed."""
        (suppression,) = suppressions_in("x = 1  # RUFF: IGNORE[s603]  # lowered.\n")
        assert (suppression.form, suppression.codes) == ("ignore", ("S603",)), (
            "the record lost the normalized form or codes"
        )
        assert suppression.written_codes == ("s603",), (
            "the record lost the spelling that decides whether Ruff honours it"
        )


class TestNoqaCasing:
    """The older spelling is partly case-insensitive, and partly not."""

    def test_an_upper_case_noqa_is_not_reported_for_its_case(self) -> None:
        """Ruff reads ``NOQA`` in any casing; the case rule must not fire."""
        assert not any(
            "case" in message for message in reported("x = 1  # NOQA: E501\n")
        ), "Ruff reads an upper-case noqa, and the contract reported its case"

    def test_a_lower_case_code_in_the_noqa_form_is_reported(self) -> None:
        """``noqa`` is case-insensitive; its code list is not.

        Measured on the pinned binary: ``# noqa: s607`` leaves S607 reported.
        Ruff draws no diagnostic for it, so only this contract would notice.
        """
        messages = reported("x = 1  # noqa: s607\n")
        assert any("case" in message for message in messages), (
            "a lower-case code, which Ruff does not match, passed the contract"
        )

    def test_a_prefixed_upper_case_noqa_still_reads_as_the_old_spelling(
        self,
    ) -> None:
        """Case must not change which form the record says was written."""
        (suppression,) = suppressions_in("x = 1  # NOQA: S607\n")
        assert suppression.form == NOQA, (
            "an upper-case noqa was recorded as a different form"
        )
