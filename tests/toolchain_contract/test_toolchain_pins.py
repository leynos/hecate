"""Contract: the detector pin is the same in the Makefile, CI, and the gate.

The version is written in three places and compared at runtime in none of
them. These tests assert the three agree without asserting any particular
version, because bumping the pin is routine while letting two definitions
drift is what produces a gate that passes locally and fails in CI.

The Makefile's own commands must also reference the version variable rather
than repeating a literal: a recipe that installs ``nose-cli@0.20.0`` while the
variable says something else is drift the comparison above cannot see.
"""

from __future__ import annotations

import re

import pytest

from .reading import (
    NOSE_TOOL,
    NOSE_VERSION_VARIABLE,
    VERSION_RE,
    ci_pin,
    gate_pin,
    makefile_pin,
    makefile_text,
    repository_files_present,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "Makefile, pyproject.toml, or CI workflow not present in this working "
        "copy (for example inside a mutation-testing sandbox that does not "
        "copy the repository root or .github/)"
    ),
)


class TestToolchainPins:
    """The coordinated pins for the nose duplication detector."""

    def test_makefile_and_ci_pin_the_same_version(self) -> None:
        """The Makefile and ci.yml must pin nose to the same version."""
        makefile_version = makefile_pin()
        ci_version = ci_pin()
        assert VERSION_RE.fullmatch(makefile_version), (
            f"Makefile {NOSE_VERSION_VARIABLE} does not look like a version: "
            f"{makefile_version!r}"
        )
        assert makefile_version == ci_version, (
            f"{NOSE_TOOL} version drift: the Makefile pins {makefile_version} "
            f"but ci.yml installs {ci_version}"
        )

    def test_gate_verifies_the_pinned_detector_version(self) -> None:
        """The gate's ``[tool.nose]`` pin must match the installed version."""
        makefile_version = makefile_pin()
        gate_version = gate_pin()
        assert VERSION_RE.fullmatch(gate_version), (
            f"[tool.nose] version does not look like a version: {gate_version!r}"
        )
        assert makefile_version == gate_version, (
            f"{NOSE_TOOL} version drift: the Makefile pins {makefile_version} "
            f"but the gate verifies {gate_version}"
        )

    @pytest.mark.parametrize(
        "usage_re",
        [
            r"'nose-cli@\$\(NOSE_VERSION\)'",
            r'"nose \$\(NOSE_VERSION\)"',
        ],
        ids=["binstall-install", "version-check"],
    )
    def test_makefile_commands_use_the_pinned_version(self, usage_re: str) -> None:
        """The Makefile's tool invocations must reference the version variable."""
        assert re.search(usage_re, makefile_text()), (
            f"the Makefile defines {NOSE_VERSION_VARIABLE} but its {NOSE_TOOL} "
            f"command does not reference it (expected pattern {usage_re})"
        )

    def test_lint_runs_the_duplication_gate(self) -> None:
        """`make lint` must run the gate, not merely offer it as a target."""
        match = re.search(r"^lint:([^\n]*)$", makefile_text(), flags=re.MULTILINE)
        assert match is not None, "the Makefile defines no lint goal"
        prerequisites = match.group(1).split()
        assert "duplication" in prerequisites, (
            "make lint must depend on the duplication gate so unsuppressed "
            f"duplication blocks the lint gate; got prerequisites {prerequisites!r}"
        )
        assert "skylos" in prerequisites, (
            "the duplication target must be added alongside the existing lint "
            f"checks, not replace them; got prerequisites {prerequisites!r}"
        )
