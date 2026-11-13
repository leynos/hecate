"""Contract: the CI uv cache covers what the tools need and is keyed on their pins.

A cache that silently stops being populated, or that restores a tool
environment a pin change should have invalidated, is invisible until a run
re-installs everything or reuses a stale environment.
"""

from __future__ import annotations

import pytest

from .reading import (
    UV_CACHE_STEP,
    cache_key,
    cache_step,
    field_entries,
    repository_files_present,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "CI workflow not present in this working copy (for example inside a "
        "mutation-testing sandbox that does not copy .github/)"
    ),
)


class TestCiCacheContract:
    """The CI cache blocks that keep tool environments between runs."""

    def test_uv_cache_covers_the_repo_local_tool_directories(self) -> None:
        """The uv cache must carry the repo-local cache and tool trees."""
        paths = field_entries(cache_step(UV_CACHE_STEP), "path")
        assert set(paths) == {".uv-cache", ".uv-tools"}, (
            "the uv cache must cover exactly the repo-local directories the "
            f"Makefile scopes uv to; got {paths!r}"
        )

    def test_uv_cache_key_hashes_every_pin_the_environment_depends_on(self) -> None:
        """The uv cache key must invalidate when a tool pin moves."""
        key = cache_key(cache_step(UV_CACHE_STEP))
        assert "hashFiles(" in key, f"the uv cache key must hash inputs, got {key!r}"
        for hashed in ("uv.lock", "Makefile", "scripts/*.py"):
            assert hashed in key, (
                f"the uv cache key must hash {hashed!r}, which pins tool "
                f"versions the cached environments depend on; got {key!r}"
            )

    def test_uv_cache_restores_to_the_same_runner_os(self) -> None:
        """A restore-key prefix must not cross operating systems."""
        keys = field_entries(cache_step(UV_CACHE_STEP), "restore-keys")
        assert any("${{ runner.os }}" in key for key in keys), (
            "the uv cache restore key must be scoped to runner.os so a cache "
            f"from another platform cannot be restored; got {keys!r}"
        )
