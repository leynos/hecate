"""Read the detector pins and the CI step structure they live in.

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
MAKEFILE_PATH = _REPO_ROOT / "Makefile"
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
NOSE_TOOL = "nose"
NOSE_VERSION_VARIABLE = f"{NOSE_TOOL.upper()}_VERSION"

#: PEP 440-flavoured shape check so an accidentally emptied pin fails
#: loudly rather than comparing two empty strings as equal.
VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[a-zA-Z0-9.+-]*)")

#: The SHA-256 the install step verifies cargo-binstall against.
SHA256_RE = re.compile(r"[0-9a-f]{64}")

#: CI runs on ubuntu-latest, so the pinned installer artefact must be the
#: x86-64 Linux musl build. Reusing it (or its checksum) for another platform
#: would verify the wrong bytes, so the artefact is asserted explicitly.
BINSTALL_ARTEFACT = "cargo-binstall-x86_64-unknown-linux-musl.tgz"

#: The two CI cache steps and the install step the Makefile pins must agree
#: with.
UV_CACHE_STEP = "Cache uv tool and script environments"
NOSE_CACHE_STEP = "Cache the pinned nose duplication detector"
NOSE_INSTALL_STEP = "Install nose duplication detector"


class ToolchainContractError(Exception):
    """Raised when a pinned file is not in the shape a rule can read.

    The rule tests treat this as a contract violation and not as an error to
    be handled: an unreadable pin means the reader and the file disagree
    about where the pin lives, which is the drift these tests exist to catch.
    """


def repository_files_present() -> bool:
    """Report whether the three pinned files exist in this working copy.

    mutmut runs ``tests/`` against ``hecate/`` from a sandbox that need not
    carry the repository root or ``.github/``, where every reader below would
    fail on a missing file rather than a drifted pin. The rule tests skip on
    a false result so a mutation run reports mutation coverage instead of an
    unrelated I/O error.
    """
    return all(
        path.exists() for path in (MAKEFILE_PATH, CI_WORKFLOW_PATH, PYPROJECT_PATH)
    )


def makefile_text() -> str:
    """Return the Makefile source."""
    return MAKEFILE_PATH.read_text(encoding="utf-8")


def workflow_text() -> str:
    """Return the CI workflow source."""
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def makefile_pin() -> str:
    """Extract the nose pinned version from the Makefile.

    Returns
    -------
    str
        The version string assigned to ``NOSE_VERSION``.

    Raises
    ------
    ToolchainContractError
        If the Makefile does not define the variable.

    """
    match = re.search(
        rf"^{re.escape(NOSE_VERSION_VARIABLE)}\s*\??=\s*(\S+)\s*$",
        makefile_text(),
        flags=re.MULTILINE,
    )
    if match is None:
        message = f"{NOSE_VERSION_VARIABLE} is not defined in the Makefile"
        raise ToolchainContractError(message)
    return match.group(1)


def ci_pin() -> str:
    """Extract the nose pinned version from the CI workflow.

    Returns
    -------
    str
        The version pinned in ci.yml as ``NOSE_VERSION``.

    Raises
    ------
    ToolchainContractError
        If ci.yml pins it zero times or more than once. Pinning it twice is
        rejected rather than taking the first: whichever value the runner
        picks is the one that installs, and a reader that silently chose
        would disagree with GitHub about which.

    """
    matches = re.findall(
        rf"^\s*{re.escape(NOSE_VERSION_VARIABLE)}:\s*['\"]([^'\"]*)['\"]\s*$",
        workflow_text(),
        flags=re.MULTILINE,
    )
    if not matches:
        message = f"ci.yml does not pin {NOSE_TOOL} via {NOSE_VERSION_VARIABLE}"
        raise ToolchainContractError(message)
    if len(matches) != 1:
        message = f"ci.yml pins {NOSE_TOOL} more than once: {matches}"
        raise ToolchainContractError(message)
    return matches[0]


def gate_pin() -> str:
    """Return the detector version the duplication gate verifies at runtime.

    Raises
    ------
    ToolchainContractError
        If ``[tool.nose]`` declares no version.

    """
    match = re.search(
        r"^\[tool\.nose\]$.*?^version\s*=\s*\"([^\"]*)\"",
        PYPROJECT_PATH.read_text(encoding="utf-8"),
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        message = "pyproject.toml does not set [tool.nose] version"
        raise ToolchainContractError(message)
    return match.group(1)


def makefile_variable(name: str) -> str:
    """Return the literal value the Makefile assigns to ``name``.

    Raises
    ------
    ToolchainContractError
        If the Makefile does not define the variable.

    """
    match = re.search(
        rf"^{re.escape(name)}\s*\??=\s*(.+?)\s*$", makefile_text(), flags=re.MULTILINE
    )
    if match is None:
        message = f"{name} is not defined in the Makefile"
        raise ToolchainContractError(message)
    return match.group(1)


def goal_body(goal: str) -> str:
    """Return the recipe lines of a Makefile goal, as one joined string.

    Returns
    -------
    str
        The goal's recipe with line continuations joined and runs of
        whitespace collapsed, so a test can search it for a flag without
        depending on how the recipe is wrapped.

    Raises
    ------
    ToolchainContractError
        If the Makefile declares no recipe for the goal.

    """
    match = re.search(
        rf"^{re.escape(goal)}:.*?\n((?:[ \t].*\n|[ \t].*)+)",
        makefile_text(),
        flags=re.MULTILINE,
    )
    if match is None:
        message = f"{goal} has no recipe in the Makefile"
        raise ToolchainContractError(message)
    return " ".join(match.group(1).replace("\\\n", " ").split())


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
