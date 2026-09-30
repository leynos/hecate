"""Unit tests for policy classification."""

from __future__ import annotations

from hecate.policy import (
    ArchitecturePolicy,
    EdgeState,
    IgnoredImport,
    ModuleGroup,
    Severity,
    coverage_severity,
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


def test_coverage_severity_warns_outside_strict_mode() -> None:
    """Coverage findings never fail a non-strict run."""
    policy = ArchitecturePolicy(groups=(), strict=False)

    for state in EdgeState:
        severity = coverage_severity(state, policy)
        assert severity is Severity.WARNING, (
            f"expected warning for {state.value} outside strict mode, got {severity}"
        )


def test_coverage_severity_fails_strict_unclassified_edges() -> None:
    """Strict mode promotes unclassified edges to errors."""
    policy = ArchitecturePolicy(groups=(), strict=True)

    severity = coverage_severity(EdgeState.UNCLASSIFIED, policy)

    assert severity is Severity.ERROR, (
        f"expected unclassified strict failure, got {severity}"
    )


def test_coverage_severity_honours_configured_unresolved_severity() -> None:
    """Strict unresolved edges use the configured severity."""
    policy = ArchitecturePolicy(
        groups=(), strict=True, unresolved_internal_severity=Severity.WARNING
    )

    severity = coverage_severity(EdgeState.UNRESOLVED, policy)

    assert severity is Severity.WARNING, (
        f"expected the configured severity to apply, got {severity}"
    )
