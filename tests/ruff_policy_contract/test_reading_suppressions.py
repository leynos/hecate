"""Contract: the suppression reader on literal text, positive and negative.

``test_suppressions`` applies the house convention to the repository, and a
passing repository scan is worth nothing unless the reader behind it can fail.
These fixtures feed literal modules to the same two functions that scan uses —
:func:`tests.ruff_policy_contract.suppressions.suppressions_in` and
:func:`tests.ruff_policy_contract.test_suppressions.violations` — so each rule
is shown to fire on the shape it forbids and to stay quiet on the shape the
project writes.

The negative fixtures are not decoration. A reader that returned nothing, or
that matched every comment, would satisfy the positive cases while clearing
the whole repository, so the accepted forms are asserted to report no problem
at all.
"""

from __future__ import annotations

import pytest

from .suppressions import NOQA, Suppression, classify, suppressions_in
from .test_suppressions import violations


def reported(source: str) -> list[str]:
    """Return the convention messages for every suppression in ``source``.

    Parameters
    ----------
    source : str
        Python source read as if it were a checked module. It is passed to
        the same reader and the same rules the repository scan uses, so a
        fixture cannot agree with a copy of the policy.

    Returns
    -------
    list[str]
        One message per broken rule, in source order. Empty means every
        suppression in the text follows the convention.

    """
    return [
        message
        for suppression in suppressions_in(source)
        for message in violations((suppression,))
    ]


class TestAcceptedForms:
    """Spellings the project uses, which must draw no message."""

    def test_a_trailing_ignore_with_a_reason_is_accepted(self) -> None:
        """The common case: the comment sits after the code it covers."""
        source = "x = 1  # ruff: ignore[E501]  # The fixture pins this width.\n"
        assert reported(source) == [], (
            "a trailing ignore carrying a reason must draw no message"
        )

    def test_an_own_line_ignore_with_a_reason_is_accepted(self) -> None:
        """The form the config scan uses, because S607 needs its own line."""
        source = "# ruff: ignore[S607]  # git comes from PATH in CI.\nx = 1\n"
        assert reported(source) == [], (
            "an own-line ignore carrying a reason must draw no message"
        )

    def test_several_codes_in_one_comment_are_each_read(self) -> None:
        """One comment may cover a call that trips more than one rule."""
        source = "x = 1  # ruff: ignore[S603, S607]  # Literal argv, no shell.\n"
        (suppression,) = suppressions_in(source)
        assert suppression.codes == ("S603", "S607"), (
            "a comment naming two codes must have both read"
        )


class TestMissingRationale:
    """``ruff: ignore[...]`` with codes but nothing a reviewer can act on."""

    @pytest.mark.parametrize(
        "comment",
        [
            "# ruff: ignore[E501]",
            "# ruff: ignore[E501]  #",
            "# ruff: ignore[E501]  #    ",
            "# ruff: ignore[E501]  # ???",
            "# ruff: ignore[E501]  # --",
        ],
    )
    def test_a_suppression_without_a_meaningful_reason_is_reported(
        self, comment: str
    ) -> None:
        """A reason of punctuation says as little as no reason at all."""
        source = f"x = 1  {comment}\n"
        messages = reported(source)
        assert [message for message in messages if "no rationale" in message], (
            f"a comment whose reason is only {comment.partition('#')[-1]!r} was "
            "accepted; a rationale of punctuation is indistinguishable from "
            "none for the next reader"
        )

    def test_the_message_names_the_line_and_the_form(self) -> None:
        """A report the author cannot locate is a report they cannot act on."""
        messages = reported("x = 1\n\n# ruff: ignore[S404]\ny = 2\n")
        assert any(
            "line 3" in message and "ignore" in message for message in messages
        ), f"the message did not locate the suppression: {messages}"


class TestBareSuppressions:
    """A suppression naming no codes hides everything the line grows."""

    @pytest.mark.parametrize(
        "comment",
        [
            "# noqa",
            "# ruff: ignore",
            "# ruff:ignore",
            "# ruff: ignore[]",
            "# ruff: ignore[,]",
        ],
        ids=[
            "bare-noqa",
            "bare-ignore",
            "bare-ignore-no-space",
            "empty-brackets",
            "separators-only",
        ],
    )
    def test_a_suppression_naming_no_codes_is_reported(self, comment: str) -> None:
        """An empty or absent code list hides whatever the line grows."""
        messages = reported(f"x = 1  {comment}\n")
        assert any("names no codes" in message for message in messages), (
            f"{comment!r} named no usable code and was accepted, so it hides "
            "every diagnostic the line grows"
        )

    @pytest.mark.parametrize(
        "comment",
        [
            "# ruff: noqa: S607",
            "# flake8: noqa",
            "#ruff:noqa",
            "# ruff: noqa",
            "# NOQA: E501",
        ],
        ids=[
            "ruff-prefixed-with-codes",
            "flake8-prefixed-bare",
            "ruff-prefixed-no-space",
            "ruff-prefixed-bare",
            "upper-case-with-codes",
        ],
    )
    def test_a_prefixed_or_upper_case_noqa_is_read_and_reported(
        self, comment: str
    ) -> None:
        """These spellings suppress, so the reader must see them.

        Measured on 0.17.3: ``# ruff: noqa: S607`` and ``# flake8: noqa`` on a
        line of their own silence the whole module, and ``noqa`` is
        case-insensitive both there and as a trailing comment. A reader that
        matched only a lower-case bare ``noqa`` would call all five prose and
        clear exactly the file-wide suppression the contract forbids.
        """
        source = f"{comment}\nimport subprocess\nsubprocess.run(['make'], check=True)\n"
        (suppression,) = suppressions_in(source)
        assert suppression.form == NOQA, (
            f"{comment!r} was read as {suppression.form!r}, so a suppression "
            "checking every following line is invisible to the contract"
        )
        assert any(
            "writes `noqa`" in message for message in violations((suppression,))
        ), f"{comment!r} was not reported as the old spelling"

    def test_a_trailing_upper_case_noqa_is_a_line_suppression(self) -> None:
        """Case does not change placement; ``# NOQA: S607`` still counts."""
        (suppression,) = suppressions_in("x = 1  # NOQA: S607\n")
        assert (suppression.form, suppression.codes) == (NOQA, ("S607",)), (
            "a trailing upper-case noqa must be read as a line suppression"
        )

    def test_a_code_list_in_noqa_form_satisfies_the_no_codes_rule(self) -> None:
        """Naming a code is a separate question from the spelling used.

        The bare-``noqa`` breadth complaint must not fire here, or the two
        rules would be one rule and a report would repeat itself.
        """
        messages = reported("x = 1  # noqa: E501\n")
        assert not any("names no codes" in message for message in messages), (
            "naming a code satisfied the breadth rule; the two rules have merged"
        )

    def test_a_bare_noqa_is_reported_as_the_old_spelling_too(self) -> None:
        """Breadth and spelling are separate rules, and are both broken."""
        messages = reported("x = 1  # noqa\n")
        assert any("writes `noqa`" in message for message in messages), (
            "a bare noqa was not reported for its generic spelling"
        )
        assert any("names no codes" in message for message in messages), (
            "a bare noqa was not reported for its breadth"
        )

    def test_a_code_list_in_noqa_form_still_draws_the_spelling_message(self) -> None:
        """Codes and a reason cannot rescue the generic spelling on its own."""
        messages = reported("x = 1  # noqa: E501\n")
        assert any("writes `noqa`" in message for message in messages), (
            "the older spelling suppresses for far more tools than Ruff and "
            "was accepted because it named a code"
        )


class TestNonCodeEntries:
    """A suppression naming a rule rather than a code.

    Ruff accepts rule names in suppression comments in preview mode, which
    this project runs. A name is version-coupled prose: it cannot be looked
    up against a code list without a second implementation of Ruff's rule
    registry, and the security check below compares codes, so a named
    security rule would slip through it. Measured on the pinned binary: a
    ``file-ignore`` naming S603's rule leaves S607 reported and S603
    silenced, which is exactly one security code suppressed.
    """

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

    def test_a_real_code_is_still_accepted(self) -> None:
        """The shape rule must not reject the codes the project uses."""
        messages = reported("x = 1  # ruff: ignore[PLW1514, RUF100]  # Both.\n")
        assert messages == [], (
            "a code list of real Ruff codes was reported as malformed"
        )


class TestBroadForms:
    """File- and block-level suppressions of a security code."""

    @pytest.mark.parametrize(
        ("form", "source"),
        [
            ("file-ignore", "# ruff: file-ignore[S603]  # Reviewed once.\n"),
            ("disable", "# ruff: disable[S603]  # Reviewed once.\n"),
            ("file-ignore", "# ruff: file-ignore[S404, S607]  # Reviewed.\n"),
        ],
        ids=["file-ignore", "disable", "several-security-codes"],
    )
    def test_a_security_code_in_a_broad_form_is_reported(
        self, form: str, source: str
    ) -> None:
        """A file or block suppression covers call sites nobody reviewed."""
        messages = reported(source)
        assert any("more than one line" in message for message in messages), (
            f"a {form} suppression of a security code was accepted, so a "
            "review covering one call site switches the guard off for the "
            f"whole region; messages were {messages}"
        )

    def test_a_broad_form_of_a_style_code_is_accepted(self) -> None:
        """Only the security codes are treated as call-site policy."""
        messages = reported("# ruff: file-ignore[E501]  # Generated table below.\n")
        assert messages == [], (
            "a file-level suppression of a style code is not call-site policy"
        )


class TestReaderBoundaries:
    """What is a comment, and what is only text that looks like one."""

    @pytest.mark.parametrize(
        "comment",
        [
            "#: ``# ruff: ignore[S404]  # Runs git.`` An own-line comment",
            "#: text ``# ruff: ignore[S607]  # x`` trailing",
            "#: `# ruff: ignore[S607]` single backticks",
            "#: see # noqa: S607 for why",
        ],
        ids=["doc-directive", "mid-prose", "single-backticks", "noqa-mid-prose"],
    )
    def test_a_directive_inside_prose_is_still_a_directive(self, comment: str) -> None:
        """Ruff 0.17 parses these, and reports them as unused suppressions.

        Measured on 0.17.3: a ``#:`` comment carrying a backticked directive is
        reported at the directive's column, and the rule still fires. A reader
        anchored to the comment start would call all four of these prose and
        clear the tree while Ruff keeps complaining.
        """
        assert suppressions_in(f"{comment}\n"), (
            f"{comment!r} was read as prose, but Ruff parses it as a directive"
        )

    def test_a_hash_inside_a_string_is_not_a_suppression(self) -> None:
        """Otherwise a test's own fixture text would fail the repository scan."""
        source = 'DOC = "# noqa"\nOTHER = "# ruff: ignore[S603]"\n'
        assert not suppressions_in(source), (
            "comment text inside a string literal was read as policy"
        )

    def test_prose_comments_are_not_suppressions(self) -> None:
        """Most comments explain code, so they must not be reported as policy."""
        source = (
            "# The gate runs one pinned binary.\n# Suppressions are policy.\nx = 1\n"
        )
        assert not suppressions_in(source), (
            "prose that explains the code was reported as a suppression"
        )

    def test_a_bracketless_directive_is_recorded_even_though_ruff_ignores_it(
        self,
    ) -> None:
        """Ruff treats ``ruff: ignore`` with no brackets as prose and does nothing.

        Measured: ``subprocess.run(['make'])  # ruff: ignore`` still reports
        S607, and RUF100 does not flag the comment as unused. A comment the
        author believes suppresses something, which in fact suppresses
        nothing, is the most dangerous kind; the reader must see it so the
        missing code list is reported.
        """
        (suppression,) = suppressions_in("x = 1  # ruff: ignore\n")
        assert not suppression.codes, (
            "a bracket-less directive names no codes, and the record must say so"
        )
        assert any(
            "names no codes" in message for message in violations((suppression,))
        ), "the missing code list was not reported"

    def test_the_form_is_recorded_in_lower_case_and_codes_upper_case(self) -> None:
        """Ruff accepts either case; the record normalizes so reports match."""
        (suppression,) = suppressions_in("x = 1  # RUFF: IGNORE[s603]  # lowered.\n")
        assert (suppression.form, suppression.codes) == ("ignore", ("S603",)), (
            "the form must be lower-cased and the code upper-cased"
        )

    def test_an_enable_directive_is_read_but_never_treated_as_broad(self) -> None:
        """``ruff: enable`` restores coverage, so it cannot hide a security code.

        The reader records it because it is a directive the gate should see;
        the broad-form rule must not, because ``enable`` is the comment that
        ends a region rather than one that opens it.
        """
        assert classify("# ruff: enable[S603]") is not None, (
            "an enable directive must be read so the gate can see it"
        )
        messages = violations(suppressions_in("# ruff: enable[S603]  # Re-armed.\n"))
        assert not any("more than one line" in message for message in messages), (
            "enable restores coverage and must never count as a broad form"
        )

    def test_an_unknown_directive_spelling_is_prose(self) -> None:
        """``ruff: ban`` is not a Ruff directive, and must not be invented."""
        assert classify("# ruff: ban[E501]") is None, (
            "an unknown directive name was invented as a suppression"
        )

    def test_a_suppression_record_keeps_its_line(self) -> None:
        """The line is what makes a report actionable, so it is asserted."""
        (only,) = suppressions_in("x = 1\ny = 2  # ruff: ignore[E501]  # width\n")
        assert isinstance(only, Suppression), "the reader returned another record type"
        assert only.line == 2, "the record lost the physical line the report must name"
