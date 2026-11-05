"""Read the committed rule inventory and the dump it is regenerated from.

The inventory is a reviewed artefact rather than a snapshot: every code in it
was looked at, and a diff against it is meant to be read line by line. Keeping
its readers apart from the configuration readers makes that distinction
visible in the package layout, and keeps each module small enough for the
repository's module-length cap.

The inventory records the resolved selection, so the two directions of the
contract use different readers. ``inventory_codes`` reads what review approved;
``enabled_rule_lines`` reads what Ruff reports now. Comparing them in both
directions is what turns a snapshot into a contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from .reading import RuffPolicyError, is_rule_code

#: The reviewed inventory, beside this module so a checkout carries it.
INVENTORY_PATH = Path(__file__).resolve().parent / "enabled_rules.txt"

#: A rule code as Ruff prints it inside ``linter.rules.enabled``.
_ENABLED_ENTRY_RE = re.compile(r"^\s+(?P<name>\S.*?) \((?P<code>[A-Z]+\d+)\),$")
_ENABLED_BLOCK_RE = re.compile(
    r"^linter\.rules\.enabled = \[$(?P<body>.*?)^\]$",
    flags=re.MULTILINE | re.DOTALL,
)


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
            message = f"unrecognized enabled-rule entry: {line!r}"
            raise RuffPolicyError(message)
        codes.append(entry.group("code"))
    return tuple(codes)


def inventory_codes(text: str) -> tuple[str, ...]:
    """Parse an inventory, ignoring comments and blank lines.

    Parameters
    ----------
    text : str
        The inventory source to parse.

    Returns
    -------
    tuple[str, ...]
        The reviewed codes, in the order the file lists them.

    Raises
    ------
    RuffPolicyError
        If a line is not a comment, blank, or a rule code. What a code looks
        like is :func:`reading.is_rule_code`, shared with the selector and
        suppression contracts: a second, looser shape here would accept an
        entry those two refuse and record it as reviewed policy.

    """
    codes: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not is_rule_code(stripped):
            message = f"unrecognized inventory entry: {line!r}"
            raise RuffPolicyError(message)
        codes.append(stripped)
    return tuple(codes)


def inventory_text() -> str:
    """Return the committed inventory source.

    Returns
    -------
    str
        The inventory file's text, header comments included.

    """
    return INVENTORY_PATH.read_text(encoding="utf-8")


def inventory_header() -> tuple[str, str]:
    """Return the recorded Ruff version and sample-file name from the header.

    The inventory is only meaningful for the binary that produced it, so the
    header records which one and the test compares it with the installed
    version. A comment-free header is a contract violation rather than a
    default, because an inventory that cannot say what produced it cannot be
    reviewed.

    Returns
    -------
    tuple[str, str]
        The recorded Ruff version and the sampled module's path.

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
