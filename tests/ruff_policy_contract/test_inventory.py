"""Contract: the Ruff rule selection is the reviewed inventory.

The configuration states its policy twice over: prefixes decide which stable
rules are in scope, and ``extend-select`` names the preview rules adopted on
top. Neither list is what Ruff selects. Ruff resolves them, plus
``extend-ignore``, into a set that exists only at run time, and that set is
what a dependency bump can change without a line of this repository moving.
``per-file-ignores`` is applied when each file is checked and does not alter
that set, so it is outside this inventory.

These tests compare the resolved set against the committed inventory in both
directions, pin that inventory to the binary that produced it, and check the
policy switches that make the comparison meaningful. A test that only
snapshotted the set would report an unreviewed addition but not the removal of
a check the project depends on, so the comparison here reports both and names
the codes in each.
"""

from __future__ import annotations

import pytest

from .discovery import (
    checked_python_files,
    directories_between,
    ruff_configuration_candidates,
)
from .inventory import (
    INVENTORY_PATH,
    enabled_rule_lines,
    inventory_codes,
    inventory_header,
    inventory_text,
)
from .reading import (
    REPO_ROOT,
    SAMPLE_FILE,
    extend_select_entries,
    installed_ruff_version,
    is_explicit_preview,
    is_preview,
    is_rule_code,
    pyproject_document,
    repository_files_present,
    settings_dump,
)

#: The committed inventory this module reads beyond the shared files. A
#: partial checkout that carries the configuration but not the inventory would
#: otherwise raise out of ``inventory_text`` instead of skipping.
REQUIRED_FILES = (INVENTORY_PATH,)

pytestmark = pytest.mark.skipif(
    not repository_files_present(*REQUIRED_FILES),
    reason=(
        "the committed rule inventory is not present in this working copy "
        "(for example inside a mutation-testing sandbox)"
    ),
)


class TestEnabledRuleInventory:
    """The resolved rule set must equal the reviewed inventory."""

    def test_inventory_matches_the_resolved_rules(self) -> None:
        """Added and removed codes are reported separately and by name."""
        resolved = enabled_rule_lines(settings_dump(SAMPLE_FILE))
        reviewed = inventory_codes(inventory_text())
        added = sorted(set(resolved) - set(reviewed))
        removed = sorted(set(reviewed) - set(resolved))
        assert not added, (
            "Ruff now enables rules the inventory does not list. That is lint "
            "policy nobody reviewed; review each code and add it to "
            f"tests/ruff_policy_contract/enabled_rules.txt: {added}"
        )
        assert not removed, (
            "Ruff no longer enables rules the inventory lists. That is house "
            "policy that stopped running; either restore the selector or "
            f"review the removal and update the inventory: {removed}"
        )

    @pytest.mark.skipif(
        not (REPO_ROOT / ".git").exists(),
        reason=(
            "the nested-configuration walk lists tracked files with Git, which "
            "a mutation-testing sandbox need not carry"
        ),
    )
    def test_one_sample_represents_every_tracked_python_file(self) -> None:
        """No nearer Ruff configuration may re-root a tracked file.

        The inventory is a single row, which is only honest while every
        tracked module resolves against the same configuration as the sample.
        Ruff stops at the nearest ancestor carrying a ``pyproject.toml`` with
        ``[tool.ruff]`` or a ``ruff.toml``, so a nested one would make the
        sample describe a policy the rest of the tree does not use.

        The walk covers every ancestor, not each file's own directory. A
        configuration two levels up governs a module just as surely as one
        beside it, and Ruff's search passes through directories that contain
        only further directories.
        """
        root = SAMPLE_FILE.parents[1]
        nested = {
            directory.relative_to(root).as_posix(): candidates
            for directory in directories_between(root, checked_python_files())
            if (candidates := ruff_configuration_candidates(directory))
        }
        assert not nested, (
            "these directories declare their own Ruff configuration, so the "
            "single inventory row no longer describes every tracked Python "
            f"file: {nested}. Add a row per configuration, or remove the "
            "nested file"
        )

    def test_inventory_has_no_duplicates(self) -> None:
        """A duplicated code would hide a one-for-one swap in the diff."""
        codes = inventory_codes(inventory_text())
        duplicated = sorted({code for code in codes if codes.count(code) > 1})
        assert not duplicated, f"the inventory repeats rule codes: {duplicated}"

    def test_inventory_records_the_binary_that_produced_it(self) -> None:
        """An inventory is only reviewable against the version it describes."""
        recorded, sample = inventory_header()
        assert recorded == installed_ruff_version(), (
            f"the inventory was produced by Ruff {recorded} but the gate runs "
            f"{installed_ruff_version()}; regenerate it and review the delta"
        )
        assert sample == SAMPLE_FILE.relative_to(SAMPLE_FILE.parents[1]).as_posix(), (
            "the inventory header must name the module whose settings it "
            f"records; got {sample!r}"
        )


class TestPreviewAdoptionPolicy:
    """The policy switches that keep preview adoption reviewable."""

    def test_explicit_preview_rules_is_enabled(self) -> None:
        """Without it, a prefix silently adopts each new preview rule."""
        assert is_explicit_preview(pyproject_document()), (
            "[tool.ruff.lint].explicit-preview-rules must stay true: the "
            "prefix selectors would otherwise acquire every preview rule a "
            "Ruff release adds, which is the failure issue #140 documents"
        )

    def test_every_adopted_preview_code_is_named_individually(self) -> None:
        """The adoption list must be codes, not prefixes, globs or truncations.

        A partial prefix such as ``PLR09`` is upper-case and ends in a digit,
        so the two cheap checks this test used to make both passed on an entry
        that is not a code at all. The whole entry is matched instead, against
        the same shape the suppression contract uses.
        """
        adopted = extend_select_entries(pyproject_document())
        assert adopted, "no preview rules are adopted explicitly"
        for entry in adopted:
            assert is_rule_code(entry), (
                "every [tool.ruff.lint].extend-select entry must be an exact "
                "rule code under explicit-preview-rules, so adoption is a "
                "reviewable line; a prefix, a glob or a truncated code is not "
                f"one code, got {entry!r}"
            )

    @pytest.mark.parametrize(
        "selector",
        ["PLR09", "PLR09112", "plr0911", "PLR0911X"],
        ids=["truncated-prefix", "five-digits", "lower-case", "trailing-letter"],
    )
    def test_a_selector_that_is_not_a_whole_code_is_refused(
        self, selector: str
    ) -> None:
        """The shape check must reject what the two cheap checks accepted.

        ``PLR09`` is upper-case and ends in a digit, so both of the original
        assertions passed on it while it names nothing.

        The cases are shapes only. ``PLR091`` follows the measured grammar and
        is still not a rule; nothing in the text of a selector can settle
        that, and the inventory comparison is what catches it. Claiming
        otherwise here would be a test that passes for the wrong reason.
        """
        assert not is_rule_code(selector), (
            f"{selector!r} is not one rule code, and the shape rule accepted "
            "it; a selector that names no rule would be recorded as reviewed "
            "preview policy"
        )

    def test_the_security_codes_the_gate_relies_on_stay_enabled(self) -> None:
        """The subprocess suppressions are only meaningful if these codes run.

        ``S404`` is preview and reaches the gate only through the explicit
        adoption list, while ``S603`` and ``S607`` are stable and arrive with
        the ``S`` prefix. Both routes are policy, so both are checked: an
        accidental prefix removal is as damaging as a dropped adoption.
        """
        enabled = set(inventory_codes(inventory_text()))
        expected = {"S404", "S603", "S607"}
        missing = sorted(expected - enabled)
        assert not missing, (
            "these codes back the house subprocess suppressions, so the "
            f"inventory must keep them enabled: {missing}"
        )

    def test_preview_stays_enabled(self) -> None:
        """Disabling preview would drop the adopted codes with the rest."""
        document = pyproject_document()
        assert is_preview(document), (
            "[tool.ruff] preview must stay true so the adopted preview codes "
            "remain active; issue #140 prohibits disabling preview wholesale"
        )
        assert is_explicit_preview(document), "explicit preview policy is absent"
