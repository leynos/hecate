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
    group_warned_by_list,
    ignore_matches,
    is_group_allowed,
    is_group_warned,
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


def test_group_warn_predicate_uses_declared_policy() -> None:
    """Warning targets are determined by the importer group."""
    groups = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain"),
            ("legacy",),
        ),
        ModuleGroup("legacy", ("pkg.legacy",), ("legacy",)),
    )

    assert is_group_warned("application", "legacy", groups)
    assert not is_group_warned("legacy", "application", groups)
    assert not is_group_warned("domain", "legacy", groups)


def test_group_warned_by_list_checks_the_declared_warn_list() -> None:
    """The warn-list predicate reads only the list it is given."""
    assert group_warned_by_list("legacy", ("legacy",))
    assert not group_warned_by_list("legacy", ("application", "domain"))


def test_warning_targets_do_not_become_allowed_targets() -> None:
    """A warned target is reported, so it is not also permitted silently.

    ``is_allowed`` decides whether an edge is silent, and ``is_warned``
    decides whether it is reported. Conflating them would make a warning
    target disappear from output or make a forbidden target pass, so the two
    predicates must stay disjoint here.
    """
    groups = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain"),
            ("legacy",),
        ),
        ModuleGroup("legacy", ("pkg.legacy",), ("legacy",)),
    )

    assert is_group_warned("application", "legacy", groups)
    assert not is_group_allowed("application", "legacy", groups), (
        "a warned target must not read as an allowed one"
    )


def test_policy_is_warned_matches_the_module_helper() -> None:
    """The policy method exposes the same warning predicate."""
    group = ModuleGroup(
        "application", ("pkg.application",), ("application",), ("legacy",)
    )
    policy = ArchitecturePolicy(groups=(group,))

    assert policy.is_warned("application", "legacy")
    assert not policy.is_warned("application", "domain")
    assert not policy.is_allowed("application", "legacy")


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
