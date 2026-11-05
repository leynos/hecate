"""Behaviour: an unreviewed preview rule stays inert; an adopted one runs.

The inventory pins the set Ruff resolves today. That alone cannot show the
policy works, because a repository whose configuration happened to match the
inventory would pass whether or not explicit selection did anything. These
fixtures put a preview violation in front of the real binary under *this
repository's own* ``pyproject.toml`` and assert the two cases differ:

* a preview rule the project has not adopted, under a prefix it does not
  select, must not fire;
* a preview rule named in the adoption list must fire.

Both cases run the same interpreter and the same configuration, so a detector
that always or never flags fails one of them. The configuration is copied
rather than restated: a fixture with its own ``select`` would keep passing
after the real policy was gutted.
"""

from __future__ import annotations

import json
import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
import textwrap
from pathlib import Path

import pytest

from .reading import (
    PYPROJECT_PATH,
    RuffPolicyError,
    extend_select_entries,
    pyproject_document,
    repository_files_present,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "pyproject.toml or the sample module is not present in this working "
        "copy (for example inside a mutation-testing sandbox)"
    ),
)

#: A preview rule this project deliberately has not adopted. It lives under
#: the ``PLW`` prefix, which the project selects nowhere, so no future edit
#: to the adoption list can quietly start enforcing it in this fixture.
UNSELECTED_CODE = "PLW1514"

#: An adopted preview rule. The docstring below breaks section order under the
#: repository's numpy convention and has no other diagnostic, so the assertion
#: is about this code alone.
ADOPTED_CODE = "D420"

_UNSELECTED_VIOLATION = textwrap.dedent(
    '''\
    def read(path):
        """Read the file."""
        with open(path) as handle:
            return handle.read()
    '''
)

_ADOPTED_VIOLATION = textwrap.dedent(
    '''\
    def report(value: int) -> int:
        """Summarise the value.

        Returns
        -------
        int
            The value.

        Parameters
        ----------
        value : int
            The value.
        """
        return value
    '''
)


def _diagnostic_codes(project: Path) -> set[str]:
    """Return the codes the gate's Ruff reports for ``project``."""
    # A literal argv with no shell: S603 does not apply to this call.
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "json", "."],
        capture_output=True,
        check=False,
        cwd=project,
        text=True,
    )
    # Ruff exits 1 when it reports a diagnostic and 0 when it does not; any
    # other status means the fixture project itself could not be checked.
    if completed.returncode not in {0, 1}:
        message = f"ruff failed on the fixture: {completed.stderr}"
        raise RuffPolicyError(message)
    return {diagnostic["code"] for diagnostic in json.loads(completed.stdout)}


def _project_with(tmp_path: Path, source: str) -> Path:
    """Create a project running this repository's Ruff policy on ``source``.

    The module lands under ``tests/`` so the fixture sees the same per-file
    ignores as the test suite it stands in for, which is where the house
    suppression policy is exercised.
    """
    (tmp_path / "pyproject.toml").write_bytes(PYPROJECT_PATH.read_bytes())
    target = tmp_path / "tests" / "preview_fixture.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return tmp_path


class TestPreviewAdoptionBehaviour:
    """What the real configuration does with one preview violation."""

    def test_an_unadopted_preview_rule_stays_inert(self, tmp_path: Path) -> None:
        """A preview rule outside every selector must not fire."""
        project = _project_with(tmp_path, _UNSELECTED_VIOLATION)
        assert UNSELECTED_CODE not in _diagnostic_codes(project), (
            f"{UNSELECTED_CODE} fired even though no selector names it. Under "
            "explicit preview adoption an unlisted preview rule must stay "
            "inert, otherwise a Ruff release can change this project's lint "
            "policy without a reviewable configuration change."
        )

    def test_an_adopted_preview_rule_is_enforced(self, tmp_path: Path) -> None:
        """A code in the adoption list must fire on its violation."""
        adopted = set(extend_select_entries(pyproject_document()))
        assert ADOPTED_CODE in adopted, (
            f"{ADOPTED_CODE} is no longer in [tool.ruff.lint].extend-select, "
            "so this fixture would assert a policy the repository does not "
            "have; update the fixture with the replacement it was migrated to"
        )
        project = _project_with(tmp_path, _ADOPTED_VIOLATION)
        assert ADOPTED_CODE in _diagnostic_codes(project), (
            f"{ADOPTED_CODE} is adopted in [tool.ruff.lint].extend-select but "
            "did not fire on a violating module. Explicit preview adoption "
            "must not disable the rules it names."
        )
