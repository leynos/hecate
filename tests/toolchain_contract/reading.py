"""Read the CI cache step structure the toolchain contracts check.

Support for the toolchain-contract tests. Everything here takes text or a
path and returns text, so the rule tests can apply a reader to a spelling
this repository does not currently use. That matters more than usual for the
CI readers: the workflow is YAML, and a field may be written either as an
indented block scalar or as an inline scalar, so a reader that only handled
the spelling in front of it would pass here and misread the next edit.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The CI cache step the contracts read.
UV_CACHE_STEP = "Cache uv tool and script environments"


class ToolchainContractError(Exception):
    """Raised when a pinned file is not in the shape a rule can read.

    The rule tests treat this as a contract violation and not as an error to
    be handled: an unreadable pin means the reader and the file disagree
    about where the pin lives, which is the drift these tests exist to catch.
    """


def repository_files_present() -> bool:
    """Report whether the CI workflow exists in this working copy.

    mutmut runs ``tests/`` against ``hecate/`` from a sandbox that need not
    carry the repository root or ``.github/``, where every reader below would
    fail on a missing file rather than a drifted pin. The rule tests skip on
    a false result so a mutation run reports mutation coverage instead of an
    unrelated I/O error.
    """
    return CI_WORKFLOW_PATH.exists()


def workflow_text() -> str:
    """Return the CI workflow source."""
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def cache_step(name: str) -> str:
    """Return one CI step, from its ``- name:`` to the start of the next.

    Returns
    -------
    str
        The YAML block for the named step, without trailing blank lines.

    Raises
    ------
    ValueError
        If no step carries that name, which is a reader or workflow bug
        rather than a drifted value.

    """
    text = workflow_text()
    start = text.index(f"      - name: {name}")
    end = text.find("\n      - name:", start + 1)
    return text[start:] if end == -1 else text[start:end].rstrip()


def cache_key(step: str) -> str:
    """Extract the ``key:`` expression from a cache step.

    Raises
    ------
    ToolchainContractError
        If the step declares no key.

    """
    match = re.search(r"^\s*key:\s*(.+?)\s*$", step, flags=re.MULTILINE)
    if match is None:
        message = f"cache step declares no key:\n{step}"
        raise ToolchainContractError(message)
    return match.group(1)


def indent_of(line: str) -> int:
    """Return the leading-whitespace width of ``line``."""
    return len(line) - len(line.lstrip())


def indented_entries(following_lines: list[str], indent: int) -> tuple[str, ...]:
    """Collect entries indented deeper than ``indent``, stopping at the block end.

    Blank lines inside the block are transparent, as they are when reading a
    YAML block scalar; the first non-blank line at or above ``indent`` ends it.

    Returns
    -------
    tuple[str, ...]
        The entries, in order and with surrounding whitespace removed.
    """
    present = (line for line in following_lines if line.strip())
    deeper = itertools.takewhile(lambda line: indent_of(line) > indent, present)
    return tuple(line.strip() for line in deeper)


def field_entries(step: str, field: str) -> tuple[str, ...]:
    """Read a step field as a list of entries, block or inline.

    A field may be written either as an indented block scalar (``path: |``,
    one entry per line) or as an inline scalar (``path: .tools/nose``). Both
    are read here so a contract test can compare entries exactly, rather than
    by substring where a mistyped path that merely contains a correct-looking
    prefix would satisfy the check.

    Returns
    -------
    tuple[str, ...]
        The field's entries, in order.

    Raises
    ------
    ToolchainContractError
        If the step declares no such field. An absent field is reported as an
        error rather than an empty result, so a renamed key fails the rule
        instead of silently satisfying a subset comparison.

    """
    lines = step.splitlines()
    inline = re.compile(rf"^\s*{re.escape(field)}:\s*(\S.*?)\s*$")
    for index, line in enumerate(lines):
        if line.strip() == f"{field}: |":
            return indented_entries(lines[index + 1 :], indent_of(line))
        match = inline.match(line)
        if match is not None:
            return (match.group(1),)
    message = f"step declares no {field} field:\n{step}"
    raise ToolchainContractError(message)
