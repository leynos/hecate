"""Judge suppressions against the house convention, without reading the tree.

``suppressions.py`` reads comments out of source; this module decides whether
what was read follows the convention. The two are separate because both the
repository scan and the literal-text fixtures need the same judgement: a
fixture that reimplemented it would prove only that the copy works, and the
copy would drift.

Nothing here reads a file or knows where the repository is. That is what lets
the fixtures call it with a string they just built, and it is why it does not
live in a test module: importing a test module evaluates its skip conditions,
so a fixture importing one would inherit the repository's presence
requirements for no reason.
"""

from __future__ import annotations

import collections.abc as cabc

from .reading import is_rule_code
from .suppressions import NOQA, Suppression

#: The codes whose breadth would hide a subprocess risk. ``S404`` guards the
#: import, ``S603`` the call, ``S607`` the lookup of a partial path; a
#: file-level or block suppression of any of them would switch that guard off
#: for more than the line the author considered.
SECURITY_CODES = frozenset({"S404", "S603", "S607"})

#: The forms that span more than one line. A security code in either is what
#: the contract forbids, because the author's review covered one call site and
#: the comment covers a region.
BROAD_FORMS = frozenset({"file-ignore", "disable"})

#: The form that ends a covered region rather than opening one. It carries no
#: rationale of its own: a ``disable``/``enable`` pair is one reviewed
#: decision, and the reason written on the ``disable`` is the reason for both.
#: Demanding a second copy would only invite the two to drift apart.
CLOSING_FORMS = frozenset({"enable"})

#: What one entry in a suppression's code list may look like is
#: ``reading.is_rule_code``, shared with the selector contract so the two
#: cannot drift apart on what a code is. Two shapes it refuses matter here.
#: Ruff accepts rule *names* in preview mode, which this project runs, and a
#: name matches no code: ``file-ignore[subprocess-without-shell-equals-true]``
#: silences S603 across the module (measured on the pinned binary, which then
#: reports only S607). And ``[S603 S607]``, a pair joined by a space where the
#: Ruff grammar wants a comma, suppresses *neither* on the pinned binary and
#: is RUF103 on 0.17.3; that check covers both, because a space-joined pair is
#: one entry.


#: What one convention rule is: a function that returns the message for a
#: suppression breaking it, or ``None`` when it is satisfied.
_Rule = cabc.Callable[[Suppression], str | None]


def _where(suppression: Suppression) -> str:
    """Return the location a report should name for ``suppression``."""
    return f"line {suppression.line} ({suppression.form})"


def _noqa_message(suppression: Suppression) -> str | None:
    """Report the older spelling, which every tool reads as a suppression."""
    if suppression.form != NOQA:
        return None
    return (
        f"{_where(suppression)}: writes `noqa`, which every tool reads; use "
        "`ruff: ignore[...]` so the suppression is this project's decision "
        "rather than a generic one"
    )


def _breadth_message(suppression: Suppression) -> str | None:
    """Report a suppression that names no code and so hides everything."""
    if suppression.codes:
        return None
    return (
        f"{_where(suppression)}: names no codes, so it hides every diagnostic "
        "the line grows, including ones nobody has reviewed yet"
    )


def _malformed_message(suppression: Suppression) -> str | None:
    """Report entries that only look like codes and so suppress nothing."""
    malformed = [code for code in suppression.codes if not is_rule_code(code)]
    if not malformed:
        return None
    return (
        f"{_where(suppression)}: {', '.join(map(repr, malformed))} is not a "
        "rule code; a rule name matches no code, so the security check cannot "
        "see what it suppresses and a Ruff release renames it silently, and a "
        "space-joined pair is not a code at all"
    )


def _rationale_message(suppression: Suppression) -> str | None:
    """Report a suppression hiding something with no stated reason."""
    if suppression.form in CLOSING_FORMS or suppression.has_reason:
        return None
    return f"{_where(suppression)}: has no rationale after a second `#`"


def _case_message(suppression: Suppression) -> str | None:
    """Report a spelling Ruff matches case-sensitively and so ignores."""
    if suppression.records_canonical_case:
        return None
    return (
        f"{_where(suppression)}: is written as {suppression.form}"
        f"[{', '.join(suppression.written_codes)}], which Ruff does not read; "
        "the prefix, the directive name and the codes are all case-sensitive, "
        "and a wrongly-cased comment suppresses nothing while looking like "
        "policy"
    )


def _broad_message(suppression: Suppression) -> str | None:
    """Report a security code hidden for more than the reviewed call site."""
    if suppression.form not in BROAD_FORMS:
        return None
    broad = sorted(SECURITY_CODES.intersection(suppression.codes))
    if not broad:
        return None
    return (
        f"{_where(suppression)}: suppresses {', '.join(broad)} for more than "
        "one line; put `ruff: ignore[...]` on each reviewed call site"
    )


#: The convention, in the order a report reads it. The rules are independent,
#: so one comment can break several and the author sees them all in one run.
_RULES: tuple[_Rule, ...] = (
    _noqa_message,
    _breadth_message,
    _malformed_message,
    _rationale_message,
    _case_message,
    _broad_message,
)


def violations(suppressions: tuple[Suppression, ...]) -> list[str]:
    """Return one message per suppression that breaks the convention.

    Parameters
    ----------
    suppressions : tuple[Suppression, ...]
        The suppressions read from one module.

    Returns
    -------
    list[str]
        A message for each broken rule, naming the line and the form. Several
        messages for one line are deliberate: a bare, unexplained ``noqa``
        breaks three rules, and a report naming only the first would leave the
        author to discover the rest on the next run.

    """
    return [
        message
        for suppression in suppressions
        for rule in _RULES
        if (message := rule(suppression)) is not None
    ]
