"""Contract: the gate runs the Ruff that ``uv.lock`` pins.

The inventory in ``enabled_rules.txt`` records one binary's resolution, and
``test_inventory`` compares it against whatever Ruff the virtualenv holds. That
comparison is only a contract while the virtualenv is built from the lock: a
``make build`` free to re-resolve can install a version nobody reviewed, and
the inventory test would then fail for a reason that has nothing to do with
the rule selection.

Two things make the version reproducible, so both are checked. ``uv sync``
must be given ``--locked``, which makes it refuse a lockfile whose content
would have to change; and the version the lock names must be the version the
interpreter actually imports, which is the end of the chain the inventory
points at.
"""

from __future__ import annotations

import pytest

from .provenance import goal_body, lock_text, locked_ruff_version
from .reading import (
    RuffPolicyError,
    installed_ruff_version,
    repository_files_present,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "pyproject.toml or the sample module is not present in this working "
        "copy (for example inside a mutation-testing sandbox)"
    ),
)


class TestLockedBinary:
    """The lockfile, the build recipe, and the binary must name one version."""

    def test_the_lock_pins_the_ruff_the_gate_runs(self) -> None:
        """A lock and a virtualenv that disagree mean the inventory is stale."""
        locked = locked_ruff_version(lock_text())
        installed = installed_ruff_version()
        assert locked == installed, (
            f"uv.lock pins Ruff {locked} but the gate runs {installed}. The "
            "virtualenv was not built from the lock, so the rule inventory "
            "describes neither version; run `make build` and review whatever "
            "it changes"
        )

    def test_the_build_goal_refuses_to_re_resolve(self) -> None:
        """Without ``--locked``, ``make build`` may change the gate's Ruff."""
        recipe = goal_body("build").split()
        assert "--locked" in recipe, (
            "the build target must run `uv sync --locked` so a lockfile that "
            "no longer matches the resolution fails instead of silently "
            f"installing a different Ruff; the recipe is: {' '.join(recipe)}"
        )


class TestGoalReader:
    """The Makefile reader the build check depends on."""

    def test_reads_the_recipe_with_continuations_joined(self) -> None:
        """The sync flags must survive the reader, not just the goal name.

        The interpreter is spelled ``$(UV)`` in the recipe, so the fragment
        asserted is the flag sequence rather than the whole command line.
        """
        assert "sync --locked --group dev" in goal_body("build"), (
            "the `build` recipe does not contain `sync --locked --group dev`; "
            "either `goal_body` dropped a flag while joining continuations, "
            "or the `build` recipe changed its `uv sync` flags"
        )

    def test_rejects_a_goal_that_has_no_recipe(self) -> None:
        """A renamed target must fail, not compare an empty recipe as clean."""
        with pytest.raises(RuffPolicyError, match="no recipe"):
            goal_body("no-such-goal-exists")
