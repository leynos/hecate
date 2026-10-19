"""Contract tests for the directories the Python gates reach.

The gate modules live under ``scripts/``, beside the repository's other
tooling rather than inside the ``hecate`` package, so they are formatted,
linted and type checked as a second target list. That list once named five
individual modules by hand, and ``scripts/tests/`` was added beside them
without ever being included: the suite ran in CI, but no formatter, linter or
type checker ever read the files. The gap was invisible because ``make
check-fmt`` still exited zero.

Naming the directory whole is what closes that class of gap. This module pins
the directory-level declaration, and checks it against the recipes that must
consume it, so a future hand-written module list has to be a deliberate edit
to these tests rather than an accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = _REPO_ROOT / "Makefile"

pytestmark = pytest.mark.skipif(
    not MAKEFILE_PATH.exists(),
    reason="Makefile not present in this working copy",
)

#: Every recipe that must reach the gate tooling. Each entry pairs the target
#: with the command that reads its variable, because a target that stopped
#: passing the variable would leave the directory ungated just as surely as a
#: variable that named the wrong paths.
_GATED_TARGETS = (
    ("fmt", "ruff format"),
    ("check-fmt", "ruff format --check"),
    ("lint-python", "ruff check"),
    ("typecheck", "ty check"),
)


def _makefile_text() -> str:
    """Return the Makefile with its line continuations joined."""
    return MAKEFILE_PATH.read_text(encoding="utf-8").replace("\\\n", " ")


def _makefile_variable(name: str) -> str:
    """Return the value assigned to a Makefile variable."""
    match = re.search(
        rf"^{re.escape(name)}\s*\??=\s*(.+)$",
        _makefile_text(),
        flags=re.MULTILINE,
    )
    assert match is not None, f"{name} is not defined in the Makefile"
    return match.group(1).strip()


def test_gate_targets_name_the_scripts_directory_whole() -> None:
    """The gate target must be the directory, not a hand-written module list.

    A list of modules is the shape that failed: it can only cover what someone
    remembered to add. Naming ``scripts`` means every file Ruff does not
    exclude is covered the moment it is created.
    """
    targets = _makefile_variable("GATE_PYTHON_TARGETS").split()

    assert targets == ["scripts"], (
        "GATE_PYTHON_TARGETS must name scripts/ whole: a per-module list "
        f"silently skips files added beside them. Found: {targets}"
    )


@pytest.mark.parametrize(("target", "command"), _GATED_TARGETS)
def test_every_gate_recipe_reaches_the_scripts_directory(
    target: str, command: str
) -> None:
    """Each formatting, lint and typecheck recipe must read the gate target.

    Pinning the variable alone is not enough: a recipe that dropped
    ``$(GATE_PYTHON_TARGETS)`` would leave the directory ungated while the
    variable still read correctly.
    """
    match = re.search(
        rf"^{re.escape(target)}:.*?(?=^\S)",
        _makefile_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{target} is not defined in the Makefile"

    recipe = match.group(0)
    assert f"{command} $(GATE_PYTHON_TARGETS)" in recipe, (
        f"{target} must run `{command} $(GATE_PYTHON_TARGETS)`, so files "
        "under scripts/ are actually read."
    )
