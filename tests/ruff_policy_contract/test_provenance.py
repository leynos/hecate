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

from pathlib import Path

import pytest

from . import provenance
from .provenance import (
    lock_text,
    locked_ruff_version,
    makefile_text,
    recipe_text,
)
from .reading import (
    REPO_ROOT,
    RuffPolicyError,
    installed_ruff_version,
    repository_files_present,
)

#: The files this module reads beyond the ones every contract needs. The
#: shared predicate only covers the configuration and the sampled module, so
#: naming these here is what makes a partial checkout skip instead of raising
#: ``RuffPolicyError`` out of ``lock_text`` or ``makefile_text``.
REQUIRED_FILES = (REPO_ROOT / "uv.lock", REPO_ROOT / "Makefile")

pytestmark = pytest.mark.skipif(
    not repository_files_present(*REQUIRED_FILES),
    reason=(
        "a file the provenance contract reads is not present in this working "
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
        recipe = recipe_text(makefile_text(), "build").split()
        assert "--locked" in recipe, (
            "the build target must run `uv sync --locked` so a lockfile that "
            "no longer matches the resolution fails instead of silently "
            f"installing a different Ruff; the recipe is: {' '.join(recipe)}"
        )


class TestRecipeReader:
    """The Makefile reader the build check depends on, held to literal text.

    The cases drive it with a Makefile spelled here rather than with the
    repository's own. That is the point of the separation: a reader whose only
    input is the real file cannot be shown what it does with a continuation, a
    tab-indented command or a missing goal without the repository being edited,
    and a case that needed that would be measuring the Makefile instead of the
    reader.
    """

    _MAKEFILE = (
        "build:\n\tuv sync --locked \\\n\t\t--group dev\n\ntest:\n\tuv run pytest\n"
    )

    def test_reads_the_recipe_with_continuations_joined(self) -> None:
        """The sync flags must survive the reader, not just the goal name.

        The interpreter is spelled ``$(UV)`` in the repository's recipe, so the
        fragment asserted there is the flag sequence rather than the whole
        command line. Here the continuation is the thing under test.
        """
        assert recipe_text(self._MAKEFILE, "build") == (
            "uv sync --locked --group dev"
        ), (
            "the reader did not join the continuation, so a flag on the second "
            "line of a recipe would be invisible to every caller"
        )

    def test_stops_at_the_next_goal(self) -> None:
        """A reader that ran on would report another goal's commands as this one's."""
        assert "pytest" not in recipe_text(self._MAKEFILE, "build"), (
            "the reader continued past the end of the `build` recipe and "
            "picked up the next goal's commands"
        )

    def test_rejects_a_goal_that_has_no_recipe(self) -> None:
        """A renamed target must fail, not compare an empty recipe as clean."""
        with pytest.raises(RuffPolicyError, match="no recipe"):
            recipe_text(self._MAKEFILE, "no-such-goal-exists")

    def test_a_missing_file_is_reported_as_unreadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The read boundary is separate from the parse, so it fails separately.

        The reader above cannot reach this: it never touches a path. This is the
        other half of the pre-merge ask — the file's absence surfaces here, as
        a policy error naming the file, rather than escaping as a raw
        ``FileNotFoundError`` that no contract here handles.
        """
        missing = tmp_path / "absent-Makefile"
        monkeypatch.setattr(provenance, "REPO_ROOT", tmp_path)
        with pytest.raises(RuffPolicyError, match="cannot read"):
            provenance.makefile_text()
        assert not missing.exists()
