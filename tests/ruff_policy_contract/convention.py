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
    found: list[str] = []
    for suppression in suppressions:
        where = f"line {suppression.line} ({suppression.form})"
        if suppression.form == NOQA:
            found.append(
                f"{where}: writes `noqa`, which every tool reads; use "
                "`ruff: ignore[...]` so the suppression is this project's "
                "decision rather than a generic one"
            )
        if not suppression.codes:
            found.append(
                f"{where}: names no codes, so it hides every diagnostic the "
                "line grows, including ones nobody has reviewed yet"
            )
        if malformed := [code for code in suppression.codes if not is_rule_code(code)]:
            found.append(
                f"{where}: {', '.join(map(repr, malformed))} is not a rule "
                "code; a rule name matches no code, so the security check "
                "cannot see what it suppresses and a Ruff release renames it "
                "silently, and a space-joined pair is not a code at all"
            )
        if suppression.form not in CLOSING_FORMS and not suppression.has_reason:
            found.append(f"{where}: has no rationale after a second `#`")
        if not suppression.records_canonical_case:
            found.append(
                f"{where}: is written as {suppression.form}"
                f"[{', '.join(suppression.written_codes)}], which Ruff does "
                "not read; the prefix, the directive name and the codes are "
                "all case-sensitive, and a wrongly-cased comment suppresses "
                "nothing while looking like policy"
            )
        if suppression.form in BROAD_FORMS and (
            broad := sorted(SECURITY_CODES.intersection(suppression.codes))
        ):
            found.append(
                f"{where}: suppresses {', '.join(broad)} for more than one "
                "line; put `ruff: ignore[...]` on each reviewed call site"
            )
    return found
