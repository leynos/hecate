"""Read suppression comments out of Python source, by tokenizing it.

A suppression is a comment, and a comment is not something a regular
expression can find reliably: ``"# noqa: S404"`` inside a string literal is
data, not policy, and a rule that fired on it would demand a rewrite of the
string. Tokenizing is what separates the two, so every reader here looks only
at comment tokens.

The migration these readers serve is from ``noqa`` to ``ruff: ignore[...]``.
The two spellings put the codes and the rationale in different places, so a
reader returns a small record rather than a string; a test can then name which
part of a comment it rejected instead of reporting only that the line was
wrong.

A directive is recognized wherever a ``#`` introduces one, not only at the
start of the comment. That is not a shortcut: Ruff 0.17 parses a directive
written inside prose or inside backticks and reports it as unused, so a reader
anchored to the comment start would miss real directives. The pattern follows
Ruff's grammar rather than a tidier one.
"""

from __future__ import annotations

import dataclasses as dc
import io
import re
import tokenize
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

#: The older spelling, ``noqa`` with or without a code list. The codes are
#: optional there, and a bare comment suppresses every diagnostic on the line,
#: which is the breadth the contract forbids.
#:
#: Three spellings are accepted because all three suppress, measured on
#: 0.17.3: a bare ``noqa``, one carrying a ``ruff:`` or ``flake8:`` prefix,
#: and any casing. The prefixed forms matter most. On a line of their own they
#: are **file-level** — Ruff applies them to the whole module and warns only
#: when one is trailing — so a reader that skipped them would clear a
#: suppression covering every line in the file, which is the exact breadth
#: this contract exists to refuse.
#:
#: Both patterns search rather than anchor. Ruff 0.17 finds a directive
#: anywhere in a comment that a ``#`` introduces, including inside prose and
#: inside backticks, and reports it as an unused suppression. Anchoring here
#: would make the contract under-report exactly the comments that fool their
#: authors, and Ruff's own parser is the grammar this reader is meant to model.
#: (This comment deliberately avoids writing a literal directive: Ruff parses
#: one even inside backticks, so an example here would be a live suppression.)
_NOQA_RE = re.compile(
    r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa(?![\w-])"
    r"(?::\s*(?P<codes>[A-Za-z0-9]+(?:[,\s]+[A-Za-z0-9]+)*))?",
    flags=re.IGNORECASE,
)

#: The Ruff form, a directive name with an optional bracketed code list and an
#: optional rationale after a second ``#``. An own-line comment is the same
#: token as a trailing one; what differs is where it sits relative to the
#: statement, which is a placement question rather than a reading one.
#:
#: The name must end at a delimiter, because a comment reading ``ruff:
#: ignores generated files`` is prose: measured on the pinned binary, it leaves
#: the diagnostic below it reported, so Ruff never read it as an ``ignore``.
#: Matching the prefix would report a comment nobody wrote as policy. The
#: lookahead admits a bracket, a second ``#`` starting the rationale,
#: whitespace, or the end of the token, and the trailing ``\s*`` is what lets
#: a bracketless directive with no more than a rationale stay readable — it
#: names no codes, which is the finding the contract wants to report.
#:
#: This comment deliberately does not spell a directive with its own ``#``.
#: Ruff 0.17.3 reads a directive after any ``#`` in a comment, including one
#: inside backticks, and reports RUF103 on this very text — measured, at this
#: column — so an example here would be a lint failure on the next upgrade.
_RUFF_COMMENT_RE = re.compile(
    r"#\s*ruff:\s*(?P<form>file-ignore|ignore|disable|enable)(?![\w-])"
    r"(?:\[(?P<codes>[^\]]*)\])?\s*(?:#\s*(?P<reason>.*))?",
    flags=re.IGNORECASE,
)

#: A rationale containing no letter or digit. A lone ``#`` or a run of
#: punctuation says nothing a reviewer can act on, so it counts as absent
#: rather than as a written decision.
_MEANINGLESS_REASON_RE = re.compile(r"^[^A-Za-z0-9]*$")

#: The forms only Ruff understands. ``noqa`` is the older spelling every tool
#: reads, so it is kept in the record as its own form rather than folded in.
NOQA = "noqa"


@dc.dataclass(frozen=True, slots=True)
class Suppression:
    """One suppression comment, as read from a module's tokens.

    Attributes
    ----------
    line : int
        The physical line the comment sits on, one-based.
    form : str
        ``"noqa"`` for the older spelling, otherwise the Ruff form that
        followed ``ruff:`` — ``"ignore"``, ``"file-ignore"``, ``"disable"``,
        or ``"enable"``.
    codes : tuple[str, ...]
        The codes the comment names, upper-cased, in written order. Empty when
        it names none, which for ``noqa`` is a bare suppression.
    reason : str
        The rationale text after a second ``#``, stripped. Empty when the
        comment carries none.

    """

    line: int
    form: str
    codes: tuple[str, ...]
    reason: str

    @property
    def has_reason(self) -> bool:
        """Report whether a rationale a reviewer could act on is attached."""
        return not _MEANINGLESS_REASON_RE.match(self.reason)


def split_codes(raw: str | None, *, whitespace_separates: bool) -> tuple[str, ...]:
    """Split a code list, upper-casing each code.

    The two spellings take different grammars, measured on the pinned binary.
    ``# noqa: S603 S607`` is read as two codes — RUF100 names both as
    non-enabled — while ``# ruff: ignore[S603 S607]`` suppresses *neither*:
    both diagnostics are still reported. Ruff 0.17.3 also reports the latter
    as RUF103, "missing comma between codes". Splitting the Ruff form on
    whitespace would read the comment as the suppression its author intended
    rather than the one that exists, and the shape check further down would
    never see it.

    Parameters
    ----------
    raw : str | None
        The text between the brackets, or ``None`` when the brackets were
        absent.
    whitespace_separates : bool
        Whether whitespace separates codes as well as commas. True for the
        ``noqa`` grammar, false for the ``ruff:`` directives.

    Returns
    -------
    tuple[str, ...]
        The codes, upper-cased, omitting any empty piece a stray comma left.
        A space-joined pair in the Ruff form survives as one entry, which is
        what lets the caller report the missing comma.

    """
    separator = r"[,\s]+" if whitespace_separates else r","
    return tuple(
        stripped.upper()
        for code in re.split(separator, raw or "")
        if (stripped := code.strip())
    )


def classify(comment: str) -> Suppression | None:
    """Return the suppression a comment token spells, or ``None`` for prose.

    Parameters
    ----------
    comment : str
        One comment token, including its leading ``#``.

    Returns
    -------
    Suppression | None
        The parsed record with ``line`` left at zero for the caller to fill,
        or ``None`` when the comment is not a suppression. Prose is the common
        case: most comments explain code and must not be reported as a
        malformed suppression.

    """
    if match := _NOQA_RE.search(comment):
        return Suppression(
            line=0,
            form=NOQA,
            codes=split_codes(match.group("codes"), whitespace_separates=True),
            reason="",
        )
    if match := _RUFF_COMMENT_RE.search(comment):
        return Suppression(
            line=0,
            form=match.group("form").lower(),
            codes=split_codes(match.group("codes"), whitespace_separates=False),
            reason=(match.group("reason") or "").strip(),
        )
    return None


def suppressions_in(source: str) -> tuple[Suppression, ...]:
    """Return every suppression comment in ``source``, in line order.

    Parameters
    ----------
    source : str
        Python source to read. A module that does not tokenize is the caller's
        problem: the tokenizer raises, and a contract that silently skipped an
        unparseable module would clear it without having read it.

    Returns
    -------
    tuple[Suppression, ...]
        The suppressions the module writes, in the order they appear. Comment
        tokens that are not suppressions are skipped, and a ``#`` inside a
        string literal is never a comment token, so it cannot appear here.

    """
    return tuple(
        dc.replace(parsed, line=token.start[0])
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and (parsed := classify(token.string))
    )


def scan(
    paths: cabc.Iterable[str],
    read: cabc.Callable[[str], str],
) -> cabc.Iterator[tuple[str, tuple[Suppression, ...]]]:
    """Yield each path with the suppressions its source contains.

    Parameters
    ----------
    paths : cabc.Iterable[str]
        The modules to read. Supplied by the caller so this reader never
        decides for itself which files the gate covers.
    read : cabc.Callable[[str], str]
        How to obtain one module's source. Injecting it keeps the reader
        usable against literal text in a test as well as against the
        repository's files.

    Yields
    ------
    tuple[str, tuple[Suppression, ...]]
        Each path in turn, with the suppressions found in it.

    """
    for path in paths:
        yield path, suppressions_in(read(path))
