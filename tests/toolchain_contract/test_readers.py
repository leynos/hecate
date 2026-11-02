"""Contract: the CI field reader handles both YAML spellings of a field.

The provisioning and cache contracts compare fields by exact entries rather
than by substring, so a mistyped path that merely contains a correct-looking
prefix fails. That comparison is only as good as the reader behind it. These
cases pin the four ways a field reader goes wrong: stopping early at a blank
line inside a block scalar, running past the block's end into the following
keys, missing the inline spelling, and reporting a missing field as an empty
result instead of an error.
"""

from __future__ import annotations

import pytest

from .reading import ToolchainContractError, field_entries


class TestFieldReader:
    """The field reader the provisioning and cache contracts parse CI with."""

    def test_blank_lines_inside_the_block_are_transparent(self) -> None:
        """A blank line between entries must not truncate the block."""
        step = "        path: |\n          .uv-cache\n\n          .uv-tools\n"

        assert field_entries(step, "path") == (".uv-cache", ".uv-tools"), (
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

        assert field_entries(step, "path") == (".uv-cache", ".uv-tools"), (
            "The block must end at the first line indented no deeper than its key."
        )

    def test_an_inline_scalar_is_a_single_entry(self) -> None:
        """The inline spelling must read as one entry, not an empty list."""
        step = "        path: .tools/nose\n        key: nose-${{ runner.os }}\n"

        assert field_entries(step, "path") == (".tools/nose",), (
            "An inline scalar field must be read as exactly one entry."
        )

    def test_a_step_without_the_field_is_rejected(self) -> None:
        """A missing field is an error, not an empty result."""
        step = "        key: nose-${{ runner.os }}\n"

        with pytest.raises(ToolchainContractError, match="declares no path"):
            field_entries(step, "path")
