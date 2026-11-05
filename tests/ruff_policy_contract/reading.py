"""Read the Ruff configuration and the effective rule set it resolves to.

The policy this module serves has two halves that Ruff stores in one place and
prints in neither: which codes ``pyproject.toml`` names as preview adoptions,
and what the binary actually enables after prefixes, explicit selection and
per-file ignores are applied. Both are read here so a contract test can
compare them against a committed inventory rather than trusting either alone.

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

_REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
INVENTORY_PATH = Path(__file__).resolve().parent / "enabled_rules.txt"

#: A representative source file for ``--show-settings``. The resolved settings
#: are identical for every Python file in this repository, because
#: ``per-file-ignores`` are applied after selection; one file is enough.
SAMPLE_FILE = _REPO_ROOT / "hecate" / "checker.py"

#: A rule code as Ruff prints it inside ``linter.rules.enabled``.
_ENABLED_ENTRY_RE = re.compile(r"^\s+(?P<name>\S.*?) \((?P<code>[A-Z]+\d+)\),$")
_ENABLED_BLOCK_RE = re.compile(
    r"^linter\.rules\.enabled = \[$(?P<body>.*?)^\]$",
    flags=re.MULTILINE | re.DOTALL,
)


class RuffPolicyError(Exception):
    """Raised when the configuration or Ruff's output cannot be read.

    The tests treat this as a contract violation rather than as an error to
    handle: a file this module cannot read means the reader and the file
    disagree about where the policy lives, which is exactly the drift the
    inventory exists to catch.
    """


def repository_files_present() -> bool:
    """Report whether this working copy carries the files the tests read.

    mutmut runs ``tests/`` against ``hecate/`` from a sandbox that need not
    carry the repository root or the lockfile. The rule tests skip on a false
    result so a mutation run reports mutation coverage rather than an
    unrelated I/O error.
    """
    return PYPROJECT_PATH.exists() and SAMPLE_FILE.exists()


def pyproject_text() -> str:
    """Return the repository's ``pyproject.toml`` source."""
    return PYPROJECT_PATH.read_text(encoding="utf-8")


def pyproject_document() -> cabc.Mapping[str, object]:
    """Return the parsed ``pyproject.toml``."""
    with PYPROJECT_PATH.open("rb") as handle:
        document: dict[str, object] = tomllib.load(handle)
    return document


def ruff_section(document: cabc.Mapping[str, object], *keys: str) -> object:
    """Return the nested value at ``["tool"]["ruff"][*keys]``.

    The document is typed as a read-only mapping so a literal nested table in
    a test case can pass through the same reader the real file uses; ``dict``
    is invariant in its value type and would reject every such literal.

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


def select_entries(document: cabc.Mapping[str, object]) -> tuple[str, ...]:
    """Return ``[tool.ruff.lint].select`` as written, in order.

    Raises
    ------
    RuffPolicyError
        If the setting is absent or is not a list of strings.

    """
    return _selector_list(
        ruff_section(document, "lint", "select"), "[tool.ruff.lint].select"
    )


def extend_select_entries(document: cabc.Mapping[str, object]) -> tuple[str, ...]:
    """Return ``[tool.ruff.lint].extend-select`` as written, in order."""
    return _selector_list(
        ruff_section(document, "lint", "extend-select"),
        "[tool.ruff.lint].extend-select",
    )


def is_explicit_preview(document: cabc.Mapping[str, object]) -> bool:
    """Report whether ``explicit-preview-rules`` is enabled."""
    return ruff_section(document, "lint", "explicit-preview-rules") is True


def is_preview(document: cabc.Mapping[str, object]) -> bool:
    """Report whether ``preview`` is enabled."""
    return ruff_section(document, "preview") is True


def enabled_rule_lines(settings_text: str) -> tuple[str, ...]:
    """Extract the rule codes from a ``--show-settings`` dump.

    Parameters
    ----------
    settings_text : str
        The complete standard output of ``ruff check --show-settings``.

    Returns
    -------
    tuple[str, ...]
        The codes in the order Ruff printed them.

    Raises
    ------
    RuffPolicyError
        If the dump contains no ``linter.rules.enabled`` block, or if a line
        inside the block does not look like a rule entry. Both mean Ruff's
        output changed shape and the reader would otherwise compare an empty
        set against an empty set and pass.

    """
    block = _ENABLED_BLOCK_RE.search(settings_text)
    if block is None:
        message = "the settings dump contains no linter.rules.enabled block"
        raise RuffPolicyError(message)
    codes: list[str] = []
    for line in block.group("body").splitlines():
        if not line.strip():
            continue
        entry = _ENABLED_ENTRY_RE.match(line)
        if entry is None:
            message = f"unrecognised enabled-rule entry: {line!r}"
            raise RuffPolicyError(message)
        codes.append(entry.group("code"))
    return tuple(codes)


def inventory_codes(text: str) -> tuple[str, ...]:
    """Parse an inventory, ignoring comments and blank lines.

    Raises
    ------
    RuffPolicyError
        If a line is not a comment, blank, or a rule code.

    """
    codes: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Z]+\d+", stripped):
            message = f"unrecognised inventory entry: {line!r}"
            raise RuffPolicyError(message)
        codes.append(stripped)
    return tuple(codes)


def inventory_text() -> str:
    """Return the committed inventory source."""
    return INVENTORY_PATH.read_text(encoding="utf-8")


def inventory_header() -> tuple[str, str]:
    """Return the recorded Ruff version and sample-file name from the header.

    The inventory is only meaningful for the binary that produced it, so the
    header records which one and the test compares it with the installed
    version. A comment-free header is a contract violation rather than a
    default, because an inventory that cannot say what produced it cannot be
    reviewed.

    Raises
    ------
    RuffPolicyError
        If either header field is absent.

    """
    version: str | None = None
    sample: str | None = None
    for line in inventory_text().splitlines():
        if match := re.match(r"#\s*ruff-version:\s*(\S+)\s*$", line):
            version = match.group(1)
        elif match := re.match(r"#\s*sample:\s*(\S+)\s*$", line):
            sample = match.group(1)
    if version is None or sample is None:
        message = "the inventory header must record ruff-version and sample"
        raise RuffPolicyError(message)
    return version, sample


def installed_ruff_version() -> str:
    """Return the version of the Ruff the gate runs.

    Ruff is resolved from the virtualenv that ``make build`` creates, so the
    module is invoked through this interpreter rather than through whatever
    ``ruff`` happens to be on ``PATH``.

    Raises
    ------
    RuffPolicyError
        If Ruff is not importable or its version output is unrecognised.

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
        message = f"unrecognised ruff --version output: {completed.stdout!r}"
        raise RuffPolicyError(message)
    return match.group(1)


def settings_dump(path: Path, *arguments: str) -> str:
    """Return the resolved settings Ruff reports for ``path``.

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


def locked_ruff_version(lock_text: str) -> str:
    """Return the Ruff version ``uv.lock`` pins.

    Raises
    ------
    RuffPolicyError
        If the lockfile has no ``ruff`` package entry or more than one. Two
        entries mean the lock is not the flat single-environment lock this
        test understands, and picking either would assert against a version
        the resolver may not install.

    """
    document = tomllib.loads(lock_text)
    packages = document.get("package", [])
    if not isinstance(packages, list):
        message = "uv.lock has no package list"
        raise RuffPolicyError(message)
    versions = [
        package.get("version")
        for package in packages
        if isinstance(package, dict) and package.get("name") == "ruff"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        message = f"uv.lock must pin exactly one ruff version, got {versions!r}"
        raise RuffPolicyError(message)
    return versions[0]


def lock_text() -> str:
    """Return the committed ``uv.lock`` source."""
    return (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")


def makefile_text() -> str:
    """Return the Makefile source."""
    return (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def goal_body(goal: str) -> str:
    """Return a Makefile goal's recipe with continuations joined.

    Raises
    ------
    RuffPolicyError
        If the Makefile declares no recipe for the goal.

    """
    match = re.search(
        rf"^{re.escape(goal)}:.*?\n((?:[ \t].*\n|[ \t].*)+)",
        makefile_text(),
        flags=re.MULTILINE,
    )
    if match is None:
        message = f"{goal} has no recipe in the Makefile"
        raise RuffPolicyError(message)
    return " ".join(match.group(1).replace("\\\n", " ").split())
