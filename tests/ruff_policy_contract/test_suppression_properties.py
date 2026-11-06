"""Property: the convention rules hold over generated comments, not samples.

``test_reading_suppressions`` names its cases, which is right for a truth table
whose rows each carry a reason. But the reader and the rules take text, and the
text space is open: code lists of any length, any ordering, any casing, a
rationale or none. A named case cannot say that a security code in a broad form
is *always* reported, or that a directive inside a string literal is *never*
read as policy.

These properties say exactly that, and the named cases stay beside them as the
readable specification. Hypothesis is already a project dependency, so this
costs no new tooling.

The first run of these cases failed, and the failures were mine rather than the
code's: I had keyed the assertions on words the messages do not use, and I had
assumed a lower-case code was canonically cased. Both are recorded here because
they are the reason the properties are worth having — a named case written from
the same wrong assumption would have passed.

The generated text is deliberately narrow: a comment, not a module. Feeding
Hypothesis whole Python sources would spend most of its budget on code that no
reader here is asked about, and the reader's input really is one comment token.
"""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from .convention import violations
from .suppressions import classify, suppressions_in

#: The codes the breadth rule treats as security judgements.
_SECURITY_CODES = ("S404", "S603", "S607")

#: Style codes: never named by the breadth rule, whatever form carries them.
_STYLE_CODES = ("E501", "D421", "RUF105")

#: A code as ``reading.is_rule_code`` accepts it — an upper-case prefix and
#: digits. Upper case is not incidental: the case rule measures what was
#: written against what Ruff reads, and Ruff reads codes case-sensitively, so a
#: lower-case code is a miscased one rather than a variation to tolerate.
_CODE = st.one_of(
    st.sampled_from([*_SECURITY_CODES, *_STYLE_CODES]),
    st.from_regex(r"[A-Z]{1,3}\d{1,4}", fullmatch=True),
)

#: A code list of one to four entries. Repetition is allowed because the
#: reader records what was written and the rules must not care.
_CODE_LIST = st.lists(_CODE, min_size=1, max_size=4)

#: A rationale with a letter or digit in it, which is what ``has_reason``
#: requires. ``.`` is included so the text is not always a bare word.
_RATIONALE = st.text(
    alphabet=string.ascii_letters + string.digits + " .", min_size=1, max_size=24
).filter(lambda text: any(char.isalnum() for char in text))

#: Text with no letter or digit, so it says nothing a reviewer can act on and
#: the rationale rule treats it as absent.
_MEANINGLESS = st.text(alphabet=" .,;:-_", min_size=0, max_size=8)

#: The substrings the messages actually use, named once so a reworded message
#: fails here loudly rather than silently turning an assertion vacuous.
_BROAD = "more than one line"
_RATIONALE_RULE = "no rationale"
_MALFORMED = "is not a rule code"


def _comment(codes: list[str], rationale: str | None, *, form: str = "ignore") -> str:
    """Build a canonical ``ruff:`` directive comment.

    Parameters
    ----------
    codes : list[str]
        The codes to name inside the brackets.
    rationale : str | None
        The text after a second ``#``, or ``None`` for no second ``#``.
    form : str
        The directive name; ``ignore`` unless a case says otherwise.

    Returns
    -------
    str
        One comment token, including its leading ``#``.

    """
    comment = f"# ruff: {form}[{', '.join(codes)}]"
    if rationale is not None:
        comment += f"  # {rationale}"
    return comment


def _drew(suppressions: tuple, needle: str) -> list[str]:
    """Return the violation messages containing ``needle``."""
    return [message for message in violations(suppressions) if needle in message]


class TestBroadForms:
    """Breadth is reported for security codes and never for style codes."""

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_a_security_code_in_a_broad_form_is_always_reported(
        self, codes: list[str], rationale: str
    ) -> None:
        """A ``disable``/``file-ignore`` naming a security code is refused."""
        for form in ("disable", "file-ignore"):
            comment = _comment(codes, rationale, form=form)
            parsed = classify(comment)
            assert parsed is not None, (
                f"the reader did not see a directive in {comment!r}, so the "
                "broad-form rule it feeds can never fire on generated input"
            )
            reported_broad = _drew((parsed,), _BROAD)
            names_security = any(code in _SECURITY_CODES for code in codes)
            assert bool(reported_broad) is names_security, (
                f"{comment!r} names_security={names_security} but drew "
                f"{reported_broad}; the breadth rule must fire exactly when a "
                "security code is hidden for more than the reviewed line"
            )

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_a_trailing_ignore_is_never_reported_for_breadth(
        self, codes: list[str], rationale: str
    ) -> None:
        """A scoped ``ignore`` covers its line and is not a broad form."""
        parsed = classify(_comment(codes, rationale))
        assert parsed is not None
        assert not _drew((parsed,), _BROAD), (
            f"a trailing ignore naming {codes} was reported as broad, so the "
            "rule treats a line-scoped suppression as a file-wide one"
        )


class TestRationale:
    """A rationale is reported on its own, independently of breadth."""

    @given(codes=_CODE_LIST)
    def test_a_missing_rationale_is_reported_independently(
        self, codes: list[str]
    ) -> None:
        """Naming no reason draws a message whatever codes are named."""
        comment = _comment(codes, None)
        parsed = classify(comment)
        assert parsed is not None
        assert _drew((parsed,), _RATIONALE_RULE), (
            f"{comment!r} named no rationale and drew {violations((parsed,))}, "
            "none of which asks for one"
        )

    @given(codes=_CODE_LIST, filler=_MEANINGLESS)
    def test_a_meaningless_rationale_is_treated_as_absent(
        self, codes: list[str], filler: str
    ) -> None:
        """Punctuation after the second ``#`` is not a written decision."""
        comment = _comment(codes, filler)
        parsed = classify(comment)
        assert parsed is not None
        assert _drew((parsed,), _RATIONALE_RULE), (
            f"a rationale of {filler!r} was accepted, so a comment can satisfy "
            "the rationale rule by writing punctuation"
        )

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_a_written_rationale_clears_the_rationale_rule(
        self, codes: list[str], rationale: str
    ) -> None:
        """The negative control: a real reason must silence the reason rule."""
        parsed = classify(_comment(codes, rationale))
        assert parsed is not None
        assert not _drew((parsed,), _RATIONALE_RULE), (
            f"{rationale!r} is a written rationale but was reported as absent, "
            "so the generated cases above could be passing on any text"
        )


class TestCaseAndOrdering:
    """Casing is judged against Ruff's grammar; ordering does not matter."""

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_a_canonically_written_directive_draws_no_case_message(
        self, codes: list[str], rationale: str
    ) -> None:
        """Lower-case prefix and form, upper-case codes: what Ruff reads."""
        parsed = classify(_comment(codes, rationale))
        assert parsed is not None
        assert parsed.records_canonical_case, (
            f"{_comment(codes, rationale)!r} was not recorded as canonical, so "
            "the builder does not produce the spelling this rule is about"
        )
        assert not _drew((parsed,), "case-sensitive"), (
            "a directive the reader itself writes in canonical casing drew a "
            f"case message; it drew {violations((parsed,))}"
        )

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_a_lower_case_code_is_always_miscased(
        self, codes: list[str], rationale: str
    ) -> None:
        """The complement: a code in another case suppresses nothing.

        This is the row the first run of these properties taught me to write. I
        had generated codes in any casing and asserted that none drew a case
        message; Hypothesis produced ``A0`` versus ``a0`` and showed the premise
        was mine, not the code's.
        """
        lowered = [code.lower() for code in codes]
        parsed = classify(_comment(lowered, rationale))
        assert parsed is not None
        assert not parsed.records_canonical_case, (
            f"{_comment(lowered, rationale)!r} was recorded as canonical, so a "
            "wrongly-cased code would be cleared as if Ruff read it"
        )
        assert _drew((parsed,), "case-sensitive"), (
            f"a lower-case code list {lowered} drew {violations((parsed,))}, "
            "none of which reports the casing"
        )

    @given(codes=_CODE_LIST, rationale=_RATIONALE)
    def test_code_order_does_not_change_the_verdict(
        self, codes: list[str], rationale: str
    ) -> None:
        """Reading is order-insensitive, so a reordering is not a new verdict."""
        forward = classify(_comment(codes, rationale))
        backward = classify(_comment(list(reversed(codes)), rationale))
        assert forward is not None
        assert backward is not None
        assert sorted(forward.codes) == sorted(backward.codes), (
            "reversing the code list changed the codes the reader records: "
            f"{forward.codes} against {backward.codes}"
        )
        assert len(violations((forward,))) == len(violations((backward,))), (
            "reversing the code list changed how many rules fired, so the "
            "verdict depends on the order a reviewer happened to write"
        )


class TestMalformedCodes:
    """An entry that only looks like a code is reported, whatever its place."""

    @given(
        good=st.lists(_CODE, min_size=1, max_size=3),
        bad=st.sampled_from(["S603 S607", "subprocess-without-shell-equals-true"]),
    )
    def test_a_name_or_space_joined_pair_is_always_malformed(
        self, good: list[str], bad: str
    ) -> None:
        """Both shapes suppress nothing, and both must be named as malformed."""
        parsed = classify(f"# ruff: ignore[{', '.join([*good, bad])}]  # Why.")
        assert parsed is not None
        assert _drew((parsed,), _MALFORMED), (
            f"{bad!r} beside {good} drew {violations((parsed,))}, none of "
            "which says the entry is not a code"
        )


class TestStringBoundaries:
    """Text inside a string literal is data, never a suppression."""

    @given(
        directive=st.sampled_from([
            "# ruff: ignore[S404]",
            "# noqa: S404",
            "# ruff: disable[S603]",
            "# ruff: file-ignore[S607]",
        ])
    )
    def test_a_directive_inside_a_string_is_not_read(self, directive: str) -> None:
        """Tokenizing is what separates a comment from a string's contents."""
        source = f'VALUE = "{directive} in a string"\n'
        assert not suppressions_in(source), (
            f"{directive!r} inside a string literal was read as policy; a "
            "reader that searched the text rather than the tokens would do "
            "this, and would then demand a rewrite of ordinary data"
        )

    @given(
        directive=st.sampled_from([
            "# ruff: ignore[S404]",
            "# noqa: S404",
            "# ruff: disable[S603]",
        ])
    )
    def test_the_same_directive_as_a_comment_is_read(self, directive: str) -> None:
        """The positive control for the case above: a comment is read."""
        source = f"VALUE = 1  {directive}  # Why.\n"
        assert suppressions_in(source), (
            f"{directive!r} written as a real comment was not read, so the "
            "string boundary above would pass whether or not the reader "
            "tokenizes"
        )
