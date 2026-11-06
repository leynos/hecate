"""Read the Ruff configuration and the binary that applies it.

The policy has two halves that Ruff stores in one place and prints in neither:
which codes ``pyproject.toml`` names as preview adoptions, and which rules the
binary selects once prefixes, explicit preview selection and ``extend-ignore``
are resolved. The first is read here; the second comes from the binary, whose
version and resolved settings are also read here so a contract test can pin
both. ``inventory`` reads the committed record of that resolution.

``linter.per_file_ignores`` is deliberately not read. Ruff reports it as its
own structure and applies it when checking each file, so it does not change
``linter.rules.enabled``; an inventory of that block therefore says nothing
about whether a selected rule runs on a particular path.

Everything that can be a pure function takes text or a path, so the readers
can be exercised against a configuration this repository does not contain.
"""

from __future__ import annotations

import collections.abc as cabc
import re
import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
import tomllib
import typing as typ
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

#: A representative source file for ``--show-settings``. The rule selection is
#: configuration-wide, so every Python file resolves the same enabled set and
#: one file is enough to record it. ``discovery`` checks that no nearer
#: configuration re-roots the resolution between the root and this file.
SAMPLE_FILE = REPO_ROOT / "hecate" / "checker.py"

#: The shape of one rule code, measured rather than assumed. On 0.17.3 the
#: rule set held 970 codes, every one matching ``^[A-Z]+\d+$``, with prefixes of
#: one to five letters (``ASYNC`` is the longest) and three or four digits.
#:
#: The stricter bound is what lets a contract reject a selector or suppression
#: that only looks like a code. ``PLR09`` is upper-case and ends in a digit but
#: names nothing, and a space-joined pair is two codes written with the wrong
#: separator. Both suppress nothing. The two contracts share this one
#: definition so a future Ruff prefix cannot make them disagree.
_RULE_CODE_RE = re.compile(r"[A-Z]{1,5}\d{3,4}")


class RuffPolicyError(Exception):
    """Raised when the configuration or Ruff's output cannot be read.

    The tests treat this as a contract violation rather than as an error to
    handle: a file this module cannot read means the reader and the file
    disagree about where the policy lives, which is exactly the drift the
    inventory exists to catch.
    """


def is_rule_code(entry: str) -> bool:
    """Report whether ``entry`` is exactly one rule code.

    The whole entry must match. ``re.match`` on an unanchored pattern would
    accept ``PLR09X`` for the same reason it accepts ``PLR09``: both begin with
    something code-shaped, and a selector that continues past the code is not
    a code.

    Parameters
    ----------
    entry : str
        A selector or a suppression code as it was written.

    Returns
    -------
    bool
        ``True`` only when the entire string matches the measured shape.

    """
    return _RULE_CODE_RE.fullmatch(entry) is not None


def repository_files_present(*required_paths: Path) -> bool:
    """Report whether this working copy carries the files a caller reads.

    mutmut runs ``tests/`` against ``hecate/`` from a sandbox that need not
    carry the repository root or the lockfile. The rule tests skip on a false
    result so a mutation run reports mutation coverage rather than an
    unrelated I/O error.

    Every contract reads the configuration and the sampled module, so those
    are always checked. A contract that also reads something else — the
    lockfile and the Makefile for provenance, the committed inventory for the
    rule set — must name it here. Its readers raise rather than return
    nothing, which is right for a complete checkout and is exactly the wrong
    answer for a partial one: the module would report an I/O error instead of
    skipping, and a skip reason would blame the shared files.

    Parameters
    ----------
    *required_paths : Path
        Files this caller reads beyond the two shared ones. Absent means the
        caller reads only those two.

    Returns
    -------
    bool
        ``True`` when every shared file and every named file exists.

    """
    shared = (PYPROJECT_PATH, SAMPLE_FILE)
    return all(path.exists() for path in (*shared, *required_paths))


def pyproject_text() -> str:
    """Return the repository's ``pyproject.toml`` source.

    Returns
    -------
    str
        The file's text, which the behaviour fixtures copy and edit.

    """
    return PYPROJECT_PATH.read_text(encoding="utf-8")


def pyproject_document() -> cabc.Mapping[str, object]:
    """Return the repository's ``pyproject.toml`` parsed as data.

    Returns
    -------
    cabc.Mapping[str, object]
        The parsed document, read-only so no case can edit it in place.

    """
    with PYPROJECT_PATH.open("rb") as handle:
        document: dict[str, object] = tomllib.load(handle)
    return document


def ruff_section(document: cabc.Mapping[str, object], *keys: str) -> object:
    """Return the nested value at ``["tool"]["ruff"][*keys]``.

    The document is typed as a read-only mapping so a literal nested table in
    a test case can pass through the same reader the real file uses; ``dict``
    is invariant in its value type and would reject every such literal.

    Parameters
    ----------
    document : cabc.Mapping[str, object]
        The parsed configuration to look in.
    *keys : str
        The path below ``[tool.ruff]``, one key per level.

    Returns
    -------
    object
        Whatever the configuration holds there, unvalidated: each caller
        narrows it to the shape it expects.

    Raises
    ------
    RuffPolicyError
        If any level of the path is missing, so a renamed table fails the
        contract instead of resolving to ``None`` and comparing equal to an
        absent setting.

    """
    current: object = document
    path = ("tool", "ruff", *keys)
    for index, key in enumerate(path):
        table = _table(current, path[: index + 1])
        if key not in table:
            message = f"{'.'.join(path[: index + 1])} is not defined"
            raise RuffPolicyError(message)
        current = table[key]
    return current


def _table(value: object, path: tuple[str, ...]) -> cabc.Mapping[str, object]:
    """Return ``value`` as a mapping, or fail naming the ``path`` it should be."""
    if not isinstance(value, cabc.Mapping):
        message = f"{'.'.join(path)} is not defined"
        raise RuffPolicyError(message)
    return typ.cast("cabc.Mapping[str, object]", value)


def _selector_list(value: object, name: str) -> tuple[str, ...]:
    """Return ``value`` as a tuple of selectors, or fail naming ``name``.

    A prefix selector and a prefix typo look the same to Ruff right up until
    the rule set quietly changes, so a non-string entry is a contract
    violation rather than something to stringify.
    """
    if not isinstance(value, list):
        message = f"{name} is not a list of selectors"
        raise RuffPolicyError(message)
    entries: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            message = f"{name} is not a list of selectors"
            raise RuffPolicyError(message)
        entries.append(entry)
    return tuple(entries)


def _selector_entries(
    document: cabc.Mapping[str, object], *keys: str
) -> tuple[str, ...]:
    """Return the selector list at ``[tool.ruff]`` plus ``keys``, in order.

    Parameters
    ----------
    document : cabc.Mapping[str, object]
        The parsed configuration to read.
    *keys : str
        The path below ``[tool.ruff]``, one key per level.

    Returns
    -------
    tuple[str, ...]
        The selectors, which may be prefixes, globs, or exact codes.

    Raises
    ------
    RuffPolicyError
        If the setting is absent or is not a list of strings.

    """
    name = f"[tool.ruff.{'.'.join(keys)}]"
    return _selector_list(ruff_section(document, *keys), name)


def _is_true_setting(document: cabc.Mapping[str, object], *keys: str) -> bool:
    """Report whether the setting at ``[tool.ruff]`` plus ``keys`` is true.

    Parameters
    ----------
    document : cabc.Mapping[str, object]
        The parsed configuration to read.
    *keys : str
        The path below ``[tool.ruff]``, one key per level.

    Returns
    -------
    bool
        ``True`` only for a literal TOML boolean, so a value that merely looks
        truthy cannot switch the policy on.

    """
    return ruff_section(document, *keys) is True


def select_entries(document: cabc.Mapping[str, object]) -> tuple[str, ...]:
    """Return ``[tool.ruff.lint].select`` as written, in order.

    Entries may be prefixes, globs, or exact codes; what Ruff resolves from
    them is the inventory contract's question, not this reader's.
    """
    return _selector_entries(document, "lint", "select")


def extend_select_entries(document: cabc.Mapping[str, object]) -> tuple[str, ...]:
    """Return ``[tool.ruff.lint].extend-select`` as written, in order.

    This project's policy restricts these entries to exact preview codes, so a
    prefix here would adopt rules nobody named.
    """
    return _selector_entries(document, "lint", "extend-select")


def is_explicit_preview(document: cabc.Mapping[str, object]) -> bool:
    """Report whether ``explicit-preview-rules`` is enabled.

    Only a literal TOML boolean counts: the switch is what stops a prefix
    adopting preview rules implicitly.
    """
    return _is_true_setting(document, "lint", "explicit-preview-rules")


def is_preview(document: cabc.Mapping[str, object]) -> bool:
    """Report whether ``preview`` is enabled.

    Only a literal TOML boolean counts.
    """
    return _is_true_setting(document, "preview")


def installed_ruff_version() -> str:
    """Return the version of the Ruff the gate runs.

    Ruff is resolved from the virtualenv that ``make build`` creates, so the
    module is invoked through this interpreter rather than through whatever
    ``ruff`` happens to be on ``PATH``.

    Returns
    -------
    str
        The version the virtualenv's Ruff reports, without its leading name.

    Raises
    ------
    RuffPolicyError
        If Ruff is not importable or its version output is unrecognized.

    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        message = f"cannot run the virtualenv's ruff: {error}"
        raise RuffPolicyError(message) from error
    match = re.fullmatch(r"ruff (\S+)\s*", completed.stdout)
    if match is None:
        message = f"unrecognized ruff --version output: {completed.stdout!r}"
        raise RuffPolicyError(message)
    return match.group(1)


def settings_dump(path: Path, *arguments: str) -> str:
    """Return the resolved settings Ruff reports for ``path``.

    Parameters
    ----------
    path : Path
        The file to resolve settings for. Ruff applies the configuration
        nearest to this file, so the path is what selects the policy.
    *arguments : str
        Extra ``ruff check`` arguments, inserted before the path.

    Returns
    -------
    str
        The complete standard output of ``ruff check --show-settings``.

    Raises
    ------
    RuffPolicyError
        If Ruff fails, which means the configuration itself is unreadable.

    """
    command = [sys.executable, "-m", "ruff", "check", "--show-settings", *arguments]
    try:
        completed = subprocess.run(  # ruff: ignore[S603]  # Fixed argv, no shell.
            [*command, str(path)],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        message = f"ruff could not resolve settings for {path}: {error}"
        raise RuffPolicyError(message) from error
    return completed.stdout
