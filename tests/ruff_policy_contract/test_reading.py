"""Cases: the readers reject the shapes they cannot read.

The rule tests compare the resolved rule set and the configuration against
this repository's own files. Those files use one spelling of everything, so
they cannot distinguish a working reader from one that silently returns an
empty result. These cases feed the readers text this repository does not
contain and assert that the malformed shapes raise instead of comparing equal
to nothing.

The settings reader is the one that matters most: ``--show-settings`` is a
human-readable dump, not an interface, so a Ruff release may reword or reindent
it. A reader that returned ``()`` when the block moved would make the
inventory comparison vacuous.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .discovery import (
    declares_ruff_settings,
    directories_between,
    ruff_configuration_candidates,
)
from .inventory import enabled_rule_lines, inventory_codes
from .provenance import locked_ruff_version
from .reading import RuffPolicyError, ruff_section

_SAMPLE_SETTINGS = """\
# General Settings
cache_dir = "/tmp/.ruff_cache"

linter.rules.enabled = [
\tmissing-type-function-argument (ANN001),
\tunused-import (F401),
]
linter.per_file_ignores = {}
"""


class TestEnabledRuleReader:
    """The reader over ``ruff check --show-settings`` output."""

    def test_reads_codes_in_the_order_ruff_prints_them(self) -> None:
        """Order is preserved so a regenerated inventory diffs meaningfully."""
        assert enabled_rule_lines(_SAMPLE_SETTINGS) == ("ANN001", "F401")

    def test_rejects_a_dump_without_the_enabled_block(self) -> None:
        """A moved block must fail, not silently compare empty sets."""
        with pytest.raises(RuffPolicyError, match=r"no linter\.rules\.enabled"):
            enabled_rule_lines('cache_dir = "/tmp"\n')

    def test_rejects_an_entry_it_cannot_parse(self) -> None:
        """A reformatted entry means the dump is no longer the interface read."""
        text = _SAMPLE_SETTINGS.replace(
            "\tunused-import (F401),", "\tunused-import - F401"
        )
        with pytest.raises(RuffPolicyError, match="unrecognised enabled-rule entry"):
            enabled_rule_lines(text)

    def test_stops_at_the_block_end(self) -> None:
        """Following settings must not be read as more rule entries."""
        text = _SAMPLE_SETTINGS + "linter.rules.previews = [\n\tanything (ZZZ999),\n]\n"
        assert enabled_rule_lines(text) == ("ANN001", "F401")


class TestInventoryReader:
    """The reader over the committed inventory."""

    def test_ignores_comments_and_blank_lines(self) -> None:
        """The header is prose and must not be parsed as codes."""
        text = "# generated\n\nF401\n# reviewed\nANN001\n"
        assert inventory_codes(text) == ("F401", "ANN001")

    def test_rejects_an_entry_that_is_not_a_code(self) -> None:
        """A pasted selector must not be accepted as a reviewed code."""
        with pytest.raises(RuffPolicyError, match="unrecognised inventory entry"):
            inventory_codes("F401\nD\n")

    def test_rejects_a_lowercase_or_spaced_code(self) -> None:
        """Whitespace inside an entry would otherwise disappear silently."""
        with pytest.raises(RuffPolicyError, match="unrecognised inventory entry"):
            inventory_codes("F 401\n")


class TestLockReader:
    """The reader over ``uv.lock``."""

    def test_reads_the_single_ruff_entry(self) -> None:
        """The flat lock has exactly one Ruff package to report."""
        text = """
version = 1

[[package]]
name = "ruff"
version = "0.15.13"

[[package]]
name = "ty"
version = "0.0.61"
"""
        assert locked_ruff_version(text) == "0.15.13"

    def test_rejects_a_lock_without_ruff(self) -> None:
        """A lock the reader cannot find Ruff in must fail loudly."""
        with pytest.raises(RuffPolicyError, match="exactly one ruff version"):
            locked_ruff_version('version = 1\n\n[[package]]\nname = "ty"\n')

    def test_rejects_two_ruff_entries(self) -> None:
        """Two entries mean the lock is not the flat lock this test reads."""
        text = """
[[package]]
name = "ruff"
version = "0.15.13"

[[package]]
name = "ruff"
version = "0.17.3"
"""
        with pytest.raises(RuffPolicyError, match="exactly one ruff version"):
            locked_ruff_version(text)


class TestConfigurationDiscovery:
    """The readers that decide which configuration Ruff will find."""

    def test_finds_the_ruff_toml_the_lockfile_names(self, tmp_path: Path) -> None:
        """A standalone ``ruff.toml`` is a candidate wherever it sits."""
        (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
        assert ruff_configuration_candidates(tmp_path) == ((tmp_path / "ruff.toml"),)

    def test_ignores_a_pyproject_without_ruff_settings(self, tmp_path: Path) -> None:
        """A ``pyproject.toml`` is only a Ruff config when it says so."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.1"\n', encoding="utf-8"
        )
        assert ruff_configuration_candidates(tmp_path) == ()

    def test_finds_a_pyproject_that_declares_ruff_settings(
        self, tmp_path: Path
    ) -> None:
        """``[tool.ruff]`` in a nearer project file re-roots the resolution."""
        project = tmp_path / "pyproject.toml"
        project.write_text(
            '[project]\nname = "x"\n\n[tool.ruff.lint]\nselect = ["F"]\n',
            encoding="utf-8",
        )
        assert ruff_configuration_candidates(tmp_path) == (project,)

    def test_reports_both_files_when_both_exist(self, tmp_path: Path) -> None:
        """Two candidates mean the repository cannot say which one Ruff uses."""
        (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
        project = tmp_path / "pyproject.toml"
        project.write_text("[tool.ruff]\nline-length = 88\n", encoding="utf-8")
        found = ruff_configuration_candidates(tmp_path)
        assert len(found) == 2
        assert {path.name for path in found} == {"pyproject.toml", "ruff.toml"}

    def test_unreadable_pyproject_is_not_silently_skipped(self, tmp_path: Path) -> None:
        """A malformed file must not read as "this directory configures nothing".

        Ruff would fail on such a file rather than fall back to a parent
        configuration, so a reader that skipped it would clear a directory
        Ruff actually rejects.

        """
        (tmp_path / "pyproject.toml").write_text("[tool.ruff\n", encoding="utf-8")
        with pytest.raises(RuffPolicyError, match="cannot read"):
            declares_ruff_settings(tmp_path / "pyproject.toml")


class TestDirectoryDiscovery:
    """The walk that finds every directory a file's settings pass through."""

    def test_reports_the_intermediate_directory_holding_no_module(
        self, tmp_path: Path
    ) -> None:
        """Ruff walks through a directory that contains only directories.

        A ``ruff.toml`` in ``package/`` governs ``package/inner/module.py``
        even though no module sits directly in ``package/``, so a walk that
        only visited each file's own directory would clear it.
        """
        inner = tmp_path / "package" / "inner"
        inner.mkdir(parents=True)
        module = inner / "module.py"
        module.write_text("", encoding="utf-8")
        assert directories_between(tmp_path, [module]) == (
            tmp_path / "package",
            inner,
        )

    def test_excludes_the_root_and_anything_above_it(self, tmp_path: Path) -> None:
        """The root's own configuration is the one the inventory records."""
        module = tmp_path / "module.py"
        module.write_text("", encoding="utf-8")
        assert not directories_between(tmp_path, [module])

    def test_reports_each_directory_once(self, tmp_path: Path) -> None:
        """Two files in one directory must not produce two rows for it."""
        package = tmp_path / "package"
        package.mkdir()
        files = [package / "one.py", package / "two.py"]
        assert directories_between(tmp_path, files) == (package,)


class TestRuffSectionReader:
    """The reader over the parsed configuration."""

    def test_reads_a_nested_value(self) -> None:
        """A present key resolves to its value, not to its parent table."""
        document = {"tool": {"ruff": {"lint": {"select": ["F"]}}}}
        assert ruff_section(document, "lint", "select") == ["F"]

    def test_rejects_a_missing_table(self) -> None:
        """A renamed table must not resolve to None and compare equal."""
        with pytest.raises(RuffPolicyError, match=r"tool\.ruff\.lint"):
            ruff_section({"tool": {"ruff": {}}}, "lint", "select")

    def test_rejects_a_missing_key(self) -> None:
        """A renamed key must fail at that key, not fall through to a default."""
        document = {"tool": {"ruff": {"lint": {}}}}
        with pytest.raises(
            RuffPolicyError, match=r"tool\.ruff\.lint\.select is not defined"
        ):
            ruff_section(document, "lint", "select")
