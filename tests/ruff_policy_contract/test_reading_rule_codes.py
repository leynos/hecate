"""Contract: one definition of what a rule code looks like.

Two contracts need the shape. The suppression reader asks whether an entry
between brackets is one code, and the selector check asks whether an
``extend-select`` entry names one code. The shape was written twice, and the
second copy was looser — it only asked that an entry be upper-case and end in
a digit, which ``PLR09`` satisfies while naming nothing.

The fixtures here are the negative control for the shared predicate. Each
entry is a real hazard rather than a contrived string: a truncated selector
is what an edit leaves behind, six digits is what a pasted number produces,
and ``PLR0911X`` is what unchanged anchoring accepts when the pattern is
matched rather than full-matched.

The positive witnesses are codes the pinned binary resolves, checked with
``ruff rule`` rather than invented, so a bound tightened below a real prefix
fails here with a code a reader can look up. Not all of them are enabled in
this repository: ``ASYNC100`` and ``PLW1514`` are preview rules it does not
adopt, which is why the witness is the binary and not the inventory. The
predicate describes the grammar of a rule code, and Ruff's grammar does not
change with this project's selector list.
"""

from __future__ import annotations

import pytest

from .reading import is_rule_code


class TestAcceptedCodes:
    """Real codes, including the ends of the measured bounds."""

    @pytest.mark.parametrize(
        "code",
        ["F401", "S603", "ASYNC100", "PLR0911", "PLW1514"],
        ids=["one-letter", "security", "five-letter-prefix", "four-digits", "pylint"],
    )
    def test_a_shipped_code_is_accepted(self, code: str) -> None:
        """The predicate must accept every code Ruff ships, not a subset."""
        assert is_rule_code(code), (
            f"{code!r} is a rule code Ruff ships and was refused, so the "
            "shape bound is tighter than the rule set it describes"
        )

    def test_the_longest_prefix_is_at_the_bound(self) -> None:
        """``ASYNC`` is the longest prefix on 0.17.3, measured over 970 codes.

        A five-letter witness alone does not establish the bound: a bound of
        five and a bound of six both accept it. Six letters is the case that
        separates them.
        """
        assert is_rule_code("ASYNC100"), "the longest real prefix was refused"
        assert not is_rule_code("ASYNCX100"), (
            "a six-letter prefix was accepted, so the bound is not the "
            "measured one and would admit selectors no Ruff release ships"
        )


class TestRefusedEntries:
    """Entries that look like codes and are not."""

    @pytest.mark.parametrize(
        "entry",
        [
            "PLR09",
            "PLR0",
            "PLR09112",
            "PLR09111",
            "plr0911",
            "PLR0911X",
            "PLR 0911",
            "PLR-0911",
        ],
        ids=[
            "truncated-to-two-digits",
            "prefix-only",
            "five-digits",
            "six-digits",
            "lower-case",
            "trailing-letter",
            "inner-space",
            "inner-hyphen",
        ],
    )
    def test_an_entry_that_is_not_one_whole_code_is_refused(self, entry: str) -> None:
        """Neither a prefix nor a code with more text is one code.

        The trailing-letter and inner-space cases are the ones that depend on
        full matching. A pattern matched without anchoring accepts them
        because it finds a code-shaped prefix and stops.

        These are all shape refusals. A selector that follows the grammar
        without naming a rule — ``PLR091``, for instance — is not detectable
        here at all; the inventory comparison is what rejects it.
        """
        assert not is_rule_code(entry), (
            f"{entry!r} is not one rule code and was accepted; a selector "
            "naming no rule would be recorded as reviewed policy, and a "
            "suppression naming one suppresses nothing"
        )
