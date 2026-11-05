"""Behaviour: preview adoption is explicit, and the switch is what makes it so.

The inventory pins the rule selection Ruff resolves today. That alone cannot
show the policy works: a repository whose configuration happened to match the
inventory would pass whether or not explicit selection did anything. These
fixtures therefore put the same preview violation in front of the real binary
under three versions of *this repository's own* configuration and require the
three outcomes to differ:

* the rule is enforced when its code is named in ``extend-select``;
* the rule is inert when that one adoption line is removed;
* the rule fires again once ``explicit-preview-rules`` is switched off.

The third configuration is the control. Without it, the inert case would also
pass in a repository that had never enabled the switch, and the test would
report a policy it does not have. All three copy the real configuration and
differ in exactly one line, so a change to the repository's policy moves them
together rather than leaving a hand-written fixture behind.
"""

from __future__ import annotations

import json
import re
import subprocess  # ruff: ignore[S404]  # Runs the pinned Ruff, never user input.
import sys
import textwrap
from pathlib import Path

import pytest

from .reading import (
    RuffPolicyError,
    extend_select_entries,
    pyproject_document,
    pyproject_text,
    repository_files_present,
    select_entries,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "pyproject.toml or the sample module is not present in this working "
        "copy (for example inside a mutation-testing sandbox)"
    ),
)

#: An adopted preview rule, and a docstring that violates it under the
#: repository's numpy convention with no other diagnostic, so each assertion
#: below is about this code alone.
ADOPTED_CODE = "D420"

_SECTION_ORDER_VIOLATION = textwrap.dedent(
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
    # other status means the fixture project itself could not be checked, and
    # a broken fixture must not read as a passing assertion.
    if completed.returncode not in {0, 1}:
        message = f"ruff failed on the fixture: {completed.stderr}"
        raise RuffPolicyError(message)
    return {diagnostic["code"] for diagnostic in json.loads(completed.stdout)}


def _without_adoption(configuration: str, code: str) -> str:
    """Return ``configuration`` with the line naming ``code`` removed.

    Raises
    ------
    RuffPolicyError
        Unless exactly one line names that code. Two matches mean the
        configuration is not the shape this fixture edits, and zero mean the
        rule stopped being adopted, so neither can support the comparison.

    """
    adoption = f'"{code}",'
    lines = configuration.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.strip() == adoption]
    if len(matches) != 1:
        message = f"expected one adoption line for {code}, found {len(matches)}"
        raise RuffPolicyError(message)
    del lines[matches[0]]
    return "".join(lines)


def _with_explicit_preview_disabled(configuration: str) -> str:
    """Return ``configuration`` with ``explicit-preview-rules`` switched off.

    Raises
    ------
    RuffPolicyError
        If the setting is absent. Removing it would restore the old implicit
        policy by default, so a fixture that silently accepted its absence
        would keep passing after the policy regressed.

    """
    disabled, substitutions = re.subn(
        r"(?m)^explicit-preview-rules = true$",
        "explicit-preview-rules = false",
        configuration,
    )
    if substitutions != 1:
        message = "the configuration does not enable explicit-preview-rules"
        raise RuffPolicyError(message)
    return disabled


def _project_with(tmp_path: Path, source: str, configuration: str) -> Path:
    """Write ``configuration`` and ``source`` as a throwaway project."""
    (tmp_path / "pyproject.toml").write_text(configuration, encoding="utf-8")
    target = tmp_path / "tests" / "preview_fixture.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return tmp_path


class TestPreviewAdoptionBehaviour:
    """What this repository's configuration does with one preview violation."""

    def test_an_adopted_preview_rule_is_enforced(self, tmp_path: Path) -> None:
        """A code in the adoption list must fire on its violation."""
        assert ADOPTED_CODE in extend_select_entries(pyproject_document()), (
            f"{ADOPTED_CODE} is no longer in [tool.ruff.lint].extend-select, "
            "so this fixture would assert a policy the repository does not "
            "have; update it with the replacement the rule was migrated to"
        )
        project = _project_with(tmp_path, _SECTION_ORDER_VIOLATION, pyproject_text())
        assert ADOPTED_CODE in _diagnostic_codes(project), (
            f"{ADOPTED_CODE} is adopted in [tool.ruff.lint].extend-select but "
            "did not fire on a violating module. Explicit preview adoption "
            "must not disable the rules it names."
        )

    def test_an_unadopted_preview_rule_stays_inert_under_a_selected_prefix(
        self, tmp_path: Path
    ) -> None:
        """Removing the adoption line must silence the rule it enabled."""
        # The code's own prefix stays selected in the copy, so the silence
        # below can only come from the adoption line and not from the rule
        # falling outside every prefix the project selects.
        assert "D" in select_entries(pyproject_document()), (
            f"the fixture assumes the {ADOPTED_CODE} prefix is selected"
        )
        configuration = _without_adoption(pyproject_text(), ADOPTED_CODE)
        project = _project_with(tmp_path, _SECTION_ORDER_VIOLATION, configuration)
        assert ADOPTED_CODE not in _diagnostic_codes(project), (
            f"{ADOPTED_CODE} still fired after its adoption line was removed. "
            "The selected 'D' prefix is acquiring the preview rule on its own, "
            "so a Ruff release can change this project's lint policy without "
            "a reviewable configuration change."
        )

    def test_the_explicit_switch_is_what_makes_the_rule_inert(
        self, tmp_path: Path
    ) -> None:
        """The control: under the old implicit policy the same code fires."""
        configuration = _with_explicit_preview_disabled(
            _without_adoption(pyproject_text(), ADOPTED_CODE)
        )
        project = _project_with(tmp_path, _SECTION_ORDER_VIOLATION, configuration)
        assert ADOPTED_CODE in _diagnostic_codes(project), (
            f"{ADOPTED_CODE} did not fire even with explicit-preview-rules "
            "switched off. The inert case above would then pass for a reason "
            "unrelated to this project's policy, so this control has to see "
            "the rule come back."
        )
