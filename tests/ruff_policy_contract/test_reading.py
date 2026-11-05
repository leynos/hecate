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

import pytest

from .reading import (
    RuffPolicyError,
    enabled_rule_lines,
    inventory_codes,
    locked_ruff_version,
    ruff_section,
)

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
