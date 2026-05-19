"""Unit tests for policy classification."""

from __future__ import annotations

from hecate.policy import (
    IgnoredImport,
    ModuleGroup,
    first_matching_group,
    ignore_matches,
    is_group_allowed,
)


def test_group_classification_uses_first_match() -> None:
    """The first matching group wins when prefixes overlap."""
    groups = (
        ModuleGroup("specific", ("pkg.adapters.outbound",), ("specific",)),
        ModuleGroup("general", ("pkg.adapters",), ("general",)),
    )

    assert first_matching_group("pkg.adapters.outbound.db", groups) == groups[0]


def test_allowed_group_predicate_uses_declared_policy() -> None:
    """Allowed imports are determined by the importer group."""
    groups = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup("application", ("pkg.application",), ("application", "domain")),
    )

    assert is_group_allowed("application", "domain", groups)
    assert not is_group_allowed("domain", "application", groups)


def test_ignore_matching_accepts_descendant_edges() -> None:
    """Ignores match importer and imported descendants."""
    ignored_import = IgnoredImport(
        importer="pkg.config",
        imported="pkg.adapters.outbound",
        reason="Composition root wiring.",
    )

    assert ignore_matches(
        ignored_import, "pkg.config.runtime", "pkg.adapters.outbound.db"
    )
