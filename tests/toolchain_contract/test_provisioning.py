"""Contract: provisioning fails rather than falling back to a source build.

The install recipe downloads a prebuilt binary from a GitHub release and
verifies it against a pinned checksum. Two of its properties cannot be shown
by running it on a day when the network is up: that a missing artefact fails
loudly instead of starting a costly ``cargo install``, and that the checksum
and artefact belong to the platform CI actually runs on. These tests pin
both, plus the caches that decide whether the install runs at all.

A cache that silently stops being populated, or that restores a tool
environment a pin change should have invalidated, is invisible until a run
re-installs everything or, worse, reuses a stale detector.
"""

from __future__ import annotations

import re

import pytest

from .reading import (
    BINSTALL_ARTEFACT,
    NOSE_CACHE_STEP,
    NOSE_INSTALL_STEP,
    SHA256_RE,
    UV_CACHE_STEP,
    cache_key,
    cache_step,
    field_entries,
    goal_body,
    makefile_variable,
    repository_files_present,
    workflow_text,
)

pytestmark = pytest.mark.skipif(
    not repository_files_present(),
    reason=(
        "Makefile, pyproject.toml, or CI workflow not present in this working "
        "copy (for example inside a mutation-testing sandbox that does not "
        "copy the repository root or .github/)"
    ),
)


class TestProvisioningFallbacks:
    """The provisioning must fail rather than silently build from source."""

    def test_install_recipe_prohibits_a_source_build(self) -> None:
        """The install recipe must disable the compile strategies."""
        disabled = makefile_variable("BINSTALL_DISABLE_STRATEGIES")
        assert "compile" in disabled, (
            "the install recipe must disable cargo-binstall's compile strategy "
            "so a missing trusted artefact fails loudly instead of starting a "
            f"costly source build; got {disabled!r}"
        )
        body = goal_body("install-nose")
        assert "--disable-strategies" in body, (
            "the install-nose recipe must pass --disable-strategies"
        )
        assert "$(BINSTALL_DISABLE_STRATEGIES)" in body, (
            "the install-nose recipe must use the configured disable "
            "strategies, so the prohibition is visible and testable at the "
            "variable level"
        )

    def test_install_recipe_keeps_the_binary_override(self) -> None:
        """``NOSE_BIN`` must stay overridable for a pre-provisioned probe."""
        assert "$(NOSE_TOOLS_DIR)" in makefile_variable("NOSE_BIN"), (
            "the Makefile must derive NOSE_BIN from NOSE_TOOLS_DIR so the "
            "install directory and the gate agree on one path"
        )
        gate = makefile_variable("DUPLICATION_GATE")
        assert "NOSE_BIN=" in gate, (
            "the gate invocation must export NOSE_BIN so the gate resolves the "
            "same binary the installer provisioned"
        )

    def test_ci_and_makefile_agree_on_the_install_directory(self) -> None:
        """The CI cache path must be the directory the Makefile installs into."""
        installed = makefile_variable("NOSE_TOOLS_DIR")
        cached = field_entries(cache_step(NOSE_CACHE_STEP), "path")
        assert cached == (installed,), (
            f"CI caches {cached!r} but the Makefile installs nose into "
            f"{installed!r}; a cache of the wrong directory never hits"
        )
        assert f"mkdir -p {installed}" in cache_step(NOSE_INSTALL_STEP), (
            "CI must create the detector install directory before binstall runs"
        )

    def test_ci_installs_the_pinned_detector_with_binstall(self) -> None:
        """CI must install nose through the pinned, verified binstall command."""
        step = cache_step(NOSE_INSTALL_STEP)
        assert BINSTALL_ARTEFACT in step, (
            f"CI must download the {BINSTALL_ARTEFACT} release artefact that "
            "matches its runner platform"
        )
        assert "sha256sum -c -" in step, (
            "CI must verify the downloaded installer against a pinned checksum"
        )
        versions = re.findall(r"BINSTALL_VERSION:\s*['\"]([^'\"]+)['\"]", step)
        assert len(versions) == 1, (
            f"CI must pin exactly one cargo-binstall version; got {versions!r}"
        )
        checksums = re.findall(r"BINSTALL_SHA256:\s*['\"]([^'\"]+)['\"]", step)
        assert len(checksums) == 1, (
            f"CI must pin exactly one cargo-binstall checksum; got {checksums!r}"
        )
        assert SHA256_RE.fullmatch(checksums[0]), (
            "the pinned cargo-binstall checksum must be a SHA-256 digest, got "
            f"{checksums[0]!r}"
        )
        assert "nose-cli@${NOSE_VERSION}" in step, (
            "CI must install the version-pinned nose crate, not a floating one"
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

    def test_nose_cache_key_carries_the_pinned_version(self) -> None:
        """A version bump must miss the detector cache and reinstall."""
        key = cache_key(cache_step(NOSE_CACHE_STEP))
        assert "NOSE_VERSION" in key, (
            "the detector cache key must carry the pinned version so bumping "
            f"the pin forces a reinstall; got {key!r}"
        )

    def test_ci_runs_the_gate_helper_tests(self) -> None:
        """The gate's own tests must run in CI, not only locally."""
        assert "make duplication-test" in workflow_text(), (
            "CI must run `make duplication-test` so a defect in the gate "
            "itself fails the pull request rather than only the local run"
        )
        body = goal_body("duplication-test")
        assert "-c /dev/null" in body, (
            "the helper-test target must bypass the repository pytest "
            "configuration so application plugins and conftests cannot "
            "perturb the isolated tooling run"
        )
        assert "test_atomic_write.py" in body, (
            "the helper-test target must name its test modules explicitly so "
            "an unrelated new test file cannot be swept into the run"
        )
