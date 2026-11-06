"""Contract: what a suppression's code list may contain.

The rest of the fixture suite asks whether a suppression is *placed* and
*explained* within the convention. This module asks a narrower question about
the text between the brackets, because that is where a comment can name
something the contract cannot check.

Ruff accepts rule names there in preview mode, and this project runs preview.
A name is version-coupled prose: it matches no code, so the security check that
compares codes cannot see what it suppresses. Measured on the pinned binary, a
``file-ignore`` naming S603's rule silences S603 across the module and leaves
S607 reported — one security code suppressed by a comment the contract would
otherwise clear.
"""

from __future__ import annotations

import pytest

from .reporting import reported


class TestNonCodeEntries:
    """A suppression naming something other than a rule code."""

    @pytest.mark.parametrize(
        "comment",
        [
            "# ruff: file-ignore[subprocess-without-shell-equals-true]  # Reviewed.",
            "# ruff: ignore[subprocess-without-shell-equals-true]  # Reviewed.",
            "# ruff: ignore[S60]  # Truncated code.",
        ],
        ids=["file-ignore-name", "ignore-name", "truncated-code"],
    )
    def test_an_entry_that_is_not_a_code_shape_is_reported(self, comment: str) -> None:
        """Rule names and typos must be reported, not compared as codes."""
        messages = reported(f"x = 1  {comment}\n")
        assert any("not a rule code" in message for message in messages), (
            f"{comment!r} named an entry that is not a rule code and was "
            "accepted, so it is compared as a code the security rules will "
            f"never match; messages were {messages}"
        )

    def test_a_name_in_the_noqa_form_is_reported_too(self) -> None:
        """``noqa`` takes the same selector grammar, so the same rule applies."""
        messages = reported("x = 1  # noqa: subprocess-without-shell-equals-true\n")
        assert any("not a rule code" in message for message in messages), (
            "a rule name in a noqa comment was accepted, so the two spellings "
            "are held to different code-list rules"
        )


class TestAcceptedCodeLists:
    """Shapes that are codes, including the longest prefix Ruff ships."""

    @pytest.mark.parametrize(
        "codes",
        ["PLW1514, RUF100", "S603", "ASYNC100", "E501,F401"],
        ids=["two-codes", "one-code", "five-letter-prefix", "no-space-after-comma"],
    )
    def test_a_list_of_real_codes_is_not_reported(self, codes: str) -> None:
        """The shape rule must reject names, not real codes.

        ``ASYNC100`` is the witness for the prefix bound: Ruff 0.17.3 ships
        ``ASYNC`` as its longest prefix (measured over all 970 codes), and a
        narrower bound reported a real code as malformed.
        """
        messages = reported(f"x = 1  # ruff: ignore[{codes}]  # Reviewed.\n")
        assert messages == [], (
            f"the code list {codes!r} is all real codes, and was reported as "
            f"malformed: {messages}"
        )

    def test_a_lower_case_code_is_reported_as_a_case_problem(self) -> None:
        """A lower-case code is a real code Ruff will not match.

        It is therefore reported for its case, not for its shape: the shape
        rule would say the code is not a code at all, which is false and sends
        the author looking for a different rule.
        """
        messages = reported("x = 1  # ruff: ignore[s603]  # Reviewed.\n")
        assert any("case" in message for message in messages), (
            "a lower-case code passed the contract"
        )
        assert not any("not a rule code" in message for message in messages), (
            "a real code was reported as malformed rather than as wrongly-cased"
        )


class TestSeparators:
    """The comma is required, and its absence is not a style question.

    Measured on the then-pinned 0.15.13 over a call that trips both codes: with
    ``[S603 S607]`` *both* diagnostics are still reported, so the comment
    suppresses nothing, and the comma form of the same call is silent. Ruff
    0.17.3 reports the space form as RUF103 instead. A reader that split on
    whitespace would accept a comment that never suppressed anything.
    """

    def test_a_space_joined_pair_in_the_ruff_form_is_reported(self) -> None:
        """Ruff reads the pair as neither code, so the pair is malformed."""
        messages = reported("x = 1  # ruff: ignore[S603 S607]  # Reviewed.\n")
        assert any("not a rule code" in message for message in messages), (
            "a space-joined pair was read as two codes and accepted, so a "
            "comment that suppresses nothing in Ruff passes the contract"
        )

    @pytest.mark.parametrize(
        "codes",
        ["S603 S607", "S603, S607", "S603,S607"],
        ids=["space", "comma-space", "comma"],
    )
    def test_the_noqa_form_accepts_both_separators(self, codes: str) -> None:
        """``noqa`` splits on whitespace too; RUF100 names both codes."""
        messages = reported(f"x = 1  # noqa: {codes}\n")
        assert not any("not a rule code" in message for message in messages), (
            f"the noqa grammar accepts {codes!r} and it was reported as "
            "malformed, so the two spellings are held to the wrong grammar"
        )
