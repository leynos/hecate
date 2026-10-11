"""Contract tests keeping Makefile and CI toolchain pins in sync.

The Makefile pins the ``nose`` duplication detector installed for the
``lint`` gate, and the CI workflow installs the same binary through
``cargo-binstall``. These tests assert that both places pin the same
version without asserting any specific version: bumping a pin is a routine
change, but letting the two definitions drift silently produces a gate that
passes locally and fails in CI (or the reverse).

They also pin the properties the provisioning depends on but cannot show by
running: that the installer is checksum-verified and unable to fall back to a
source build, and that the CI caches are keyed on the pins that invalidate
them. A cache that silently stops being populated, or that restores a tool
environment a pin change should have invalidated, is invisible until a run
re-installs everything or, worse, reuses a stale detector.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = _REPO_ROOT / "Makefile"
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
NOSE_TOOL = "nose"
NOSE_VERSION_VARIABLE = f"{NOSE_TOOL.upper()}_VERSION"

pytestmark = pytest.mark.skipif(
    not (
        MAKEFILE_PATH.exists() and CI_WORKFLOW_PATH.exists() and PYPROJECT_PATH.exists()
    ),
    reason=(
        "Makefile, pyproject.toml, or CI workflow not present in this working "
        "copy (for example inside a mutation-testing sandbox that does not "
        "copy the repository root or .github/)"
    ),
)

#: PEP 440-flavoured shape check so an accidentally emptied pin fails
#: loudly rather than comparing two empty strings as equal.
VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[a-zA-Z0-9.+-]*)")

#: The SHA-256 the install step verifies cargo-binstall against.
SHA256_RE = re.compile(r"[0-9a-f]{64}")

#: CI runs on ubuntu-latest, so the pinned installer artefact must be the
#: x86-64 Linux musl build. Reusing it (or its checksum) for another platform
#: would verify the wrong bytes, so the artefact is asserted explicitly.
BINSTALL_ARTEFACT = "cargo-binstall-x86_64-unknown-linux-musl.tgz"

#: The two CI cache steps whose paths and keys the Makefile pins must agree
#: with, and the Makefile variables they must agree with.
UV_CACHE_STEP = "Cache uv tool and script environments"
NOSE_CACHE_STEP = "Cache the pinned nose duplication detector"
NOSE_INSTALL_STEP = "Install nose duplication detector"


def _makefile_pin() -> str:
    """Extract the nose pinned version from the Makefile.

    Returns
    -------
    str
        The version string assigned to ``NOSE_VERSION``.
    """
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(NOSE_VERSION_VARIABLE)}\s*\??=\s*(\S+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    assert match is not None, f"{NOSE_VERSION_VARIABLE} is not defined in the Makefile"
    return match.group(1)


def _ci_pin() -> str:
    """Extract the nose pinned version from the CI workflow.

    Returns
    -------
    str
        The version pinned in ci.yml as ``NOSE_VERSION``.
    """
    text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    matches = re.findall(
        rf"^\s*{re.escape(NOSE_VERSION_VARIABLE)}:\s*['\"]([^'\"]*)['\"]\s*$",
        text,
        flags=re.MULTILINE,
    )
    assert matches, f"ci.yml does not pin {NOSE_TOOL} via {NOSE_VERSION_VARIABLE}"
    assert len(matches) == 1, f"ci.yml pins {NOSE_TOOL} more than once: {matches}"
    return matches[0]


def _gate_pin() -> str:
    """Return the detector version the duplication gate verifies at runtime."""
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^\[tool\.nose\]$.*?^version\s*=\s*\"([^\"]*)\"",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "pyproject.toml does not set [tool.nose] version"
    return match.group(1)


def _makefile_variable(name: str) -> str:
    """Return the literal value the Makefile assigns to ``name``."""
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}\s*\??=\s*(.+?)\s*$", text, flags=re.MULTILINE
    )
    assert match is not None, f"{name} is not defined in the Makefile"
    return match.group(1)


def _goal_body(goal: str) -> str:
    """Return the recipe lines of a Makefile goal, as one joined string.

    Returns
    -------
    str
        The goal's recipe with line continuations joined and runs of
        whitespace collapsed, so a test can search it for a flag without
        depending on how the recipe is wrapped.
    """
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(goal)}:.*?\n((?:[ \t].*\n|[ \t].*)+)",
        text,
        flags=re.MULTILINE,
    )
    assert match is not None, f"{goal} has no recipe in the Makefile"
    return " ".join(match.group(1).replace("\\\n", " ").split())


def _workflow_text() -> str:
    """Return the CI workflow source."""
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def _cache_step(name: str) -> str:
    """Return one CI step, from its ``- name:`` to the start of the next.

    Returns
    -------
    str
        The YAML block for the named step, without trailing blank lines.
    """
    text = _workflow_text()
    start = text.index(f"      - name: {name}")
    end = text.find("\n      - name:", start + 1)
    return text[start:] if end == -1 else text[start:end].rstrip()


def _cache_key(step: str) -> str:
    """Extract the ``key:`` expression from a cache step."""
    match = re.search(r"^\s*key:\s*(.+?)\s*$", step, flags=re.MULTILINE)
    assert match is not None, f"cache step declares no key:\n{step}"
    return match.group(1)


def _indent_of(line: str) -> int:
    """Return the leading-whitespace width of ``line``."""
    return len(line) - len(line.lstrip())


def _indented_entries(following_lines: list[str], indent: int) -> tuple[str, ...]:
    """Collect entries indented deeper than ``indent``, stopping at the block end.

    Blank lines inside the block are transparent, as they are when reading a
    YAML block scalar; the first non-blank line at or above ``indent`` ends it.

    Returns
    -------
    tuple[str, ...]
        The entries, in order and with surrounding whitespace removed.
    """
    present = (line for line in following_lines if line.strip())
    deeper = itertools.takewhile(lambda line: _indent_of(line) > indent, present)
    return tuple(line.strip() for line in deeper)


def _field_entries(step: str, field: str) -> tuple[str, ...]:
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
    AssertionError
        If the step declares no such field.

    """
    lines = step.splitlines()
    inline = re.compile(rf"^\s*{re.escape(field)}:\s*(\S.*?)\s*$")
    for index, line in enumerate(lines):
        if line.strip() == f"{field}: |":
            return _indented_entries(lines[index + 1 :], _indent_of(line))
        match = inline.match(line)
        if match is not None:
            return (match.group(1),)
    msg = f"step declares no {field} field:\n{step}"
    raise AssertionError(msg)


class TestToolchainPins:
    """The coordinated pins for the nose duplication detector."""

    def test_makefile_and_ci_pin_the_same_version(self) -> None:
        """The Makefile and ci.yml must pin nose to the same version."""
        makefile_version = _makefile_pin()
        ci_version = _ci_pin()
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
        makefile_version = _makefile_pin()
        gate_version = _gate_pin()
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
        text = MAKEFILE_PATH.read_text(encoding="utf-8")
        assert re.search(usage_re, text), (
            f"the Makefile defines {NOSE_VERSION_VARIABLE} but its {NOSE_TOOL} "
            f"command does not reference it (expected pattern {usage_re})"
        )

    def test_lint_runs_the_duplication_gate(self) -> None:
        """`make lint` must run the gate, not merely offer it as a target."""
        text = MAKEFILE_PATH.read_text(encoding="utf-8")
        match = re.search(r"^lint:([^\n]*)$", text, flags=re.MULTILINE)
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

    def test_ci_installs_the_pinned_detector_with_binstall(self) -> None:
        """CI must install nose through the pinned, verified binstall command."""
        step = _cache_step(NOSE_INSTALL_STEP)
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


class TestProvisioningFallbacks:
    """The provisioning must fail rather than silently build from source."""

    def test_install_recipe_prohibits_a_source_build(self) -> None:
        """The install recipe must disable the compile strategies."""
        disabled = _makefile_variable("BINSTALL_DISABLE_STRATEGIES")
        assert "compile" in disabled, (
            "the install recipe must disable cargo-binstall's compile strategy "
            "so a missing trusted artefact fails loudly instead of starting a "
            f"costly source build; got {disabled!r}"
        )
        body = _goal_body("install-nose")
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
        assert "$(NOSE_TOOLS_DIR)" in _makefile_variable("NOSE_BIN"), (
            "the Makefile must derive NOSE_BIN from NOSE_TOOLS_DIR so the "
            "install directory and the gate agree on one path"
        )
        gate = _makefile_variable("DUPLICATION_GATE")
        assert "NOSE_BIN=" in gate, (
            "the gate invocation must export NOSE_BIN so the gate resolves the "
            "same binary the installer provisioned"
        )

    def test_ci_and_makefile_agree_on_the_install_directory(self) -> None:
        """The CI cache path must be the directory the Makefile installs into."""
        installed = _makefile_variable("NOSE_TOOLS_DIR")
        cached = _field_entries(_cache_step(NOSE_CACHE_STEP), "path")
        assert cached == (installed,), (
            f"CI caches {cached!r} but the Makefile installs nose into "
            f"{installed!r}; a cache of the wrong directory never hits"
        )
        assert f"mkdir -p {installed}" in _cache_step(NOSE_INSTALL_STEP), (
            "CI must create the detector install directory before binstall runs"
        )


class TestFieldReader:
    """The field reader the provisioning and cache contracts parse CI with.

    The reader has to find every entry and nothing beyond the block, and it
    has to read both YAML spellings of a field. These cases pin the three ways
    that can go wrong: stopping early at a blank line inside a block, running
    past the block's end into the following keys, and missing the inline form
    the detector cache uses.
    """

    def test_blank_lines_inside_the_block_are_transparent(self) -> None:
        """A blank line between entries must not truncate the block."""
        step = "        path: |\n          .uv-cache\n\n          .uv-tools\n"

        assert _field_entries(step, "path") == (".uv-cache", ".uv-tools"), (
            "A blank line inside a block scalar must not end the block."
        )

    def test_the_block_ends_at_the_first_dedented_line(self) -> None:
        """Entries must not leak in from the lines that follow the block."""
        step = (
            "        path: |\n"
            "          .uv-cache\n"
            "          .uv-tools\n"
            "        key: uv-envs-${{ runner.os }}-\n"
        )

        assert _field_entries(step, "path") == (".uv-cache", ".uv-tools"), (
            "The block must end at the first line indented no deeper than its key."
        )

    def test_an_inline_scalar_is_a_single_entry(self) -> None:
        """The inline spelling must read as one entry, not an empty list."""
        step = "        path: .tools/nose\n        key: nose-${{ runner.os }}\n"

        assert _field_entries(step, "path") == (".tools/nose",), (
            "An inline scalar field must be read as exactly one entry."
        )

    def test_a_step_without_the_field_is_rejected(self) -> None:
        """A missing field is an error, not an empty result."""
        step = "        key: nose-${{ runner.os }}\n"

        with pytest.raises(AssertionError, match="declares no path"):
            _field_entries(step, "path")


class TestCiCacheContract:
    """The CI cache blocks that keep tool environments between runs."""

    def test_uv_cache_covers_the_repo_local_tool_directories(self) -> None:
        """The uv cache must carry the repo-local cache and tool trees."""
        paths = _field_entries(_cache_step(UV_CACHE_STEP), "path")
        assert set(paths) == {".uv-cache", ".uv-tools"}, (
            "the uv cache must cover exactly the repo-local directories the "
            f"Makefile scopes uv to; got {paths!r}"
        )

    def test_uv_cache_key_hashes_every_pin_the_environment_depends_on(self) -> None:
        """The uv cache key must invalidate when a tool pin moves."""
        key = _cache_key(_cache_step(UV_CACHE_STEP))
        assert "hashFiles(" in key, f"the uv cache key must hash inputs, got {key!r}"
        for hashed in ("uv.lock", "Makefile", "scripts/*.py"):
            assert hashed in key, (
                f"the uv cache key must hash {hashed!r}, which pins tool "
                f"versions the cached environments depend on; got {key!r}"
            )

    def test_uv_cache_restores_to_the_same_runner_os(self) -> None:
        """A restore-key prefix must not cross operating systems."""
        keys = _field_entries(_cache_step(UV_CACHE_STEP), "restore-keys")
        assert any("${{ runner.os }}" in key for key in keys), (
            "the uv cache restore key must be scoped to runner.os so a cache "
            f"from another platform cannot be restored; got {keys!r}"
        )

    def test_nose_cache_key_carries_the_pinned_version(self) -> None:
        """A version bump must miss the detector cache and reinstall."""
        key = _cache_key(_cache_step(NOSE_CACHE_STEP))
        assert "NOSE_VERSION" in key, (
            "the detector cache key must carry the pinned version so bumping "
            f"the pin forces a reinstall; got {key!r}"
        )

    def test_ci_runs_the_gate_helper_tests(self) -> None:
        """The gate's own tests must run in CI, not only locally."""
        assert "make duplication-test" in _workflow_text(), (
            "CI must run `make duplication-test` so a defect in the gate "
            "itself fails the pull request rather than only the local run"
        )
        body = _goal_body("duplication-test")
        assert "-c /dev/null" in body, (
            "the helper-test target must bypass the repository pytest "
            "configuration so application plugins and conftests cannot "
            "perturb the isolated tooling run"
        )
        assert "test_atomic_write.py" in body, (
            "the helper-test target must name its test modules explicitly so "
            "an unrelated new test file cannot be swept into the run"
        )
