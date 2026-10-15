"""Unit tests for policy classification."""

from __future__ import annotations

from hecate.policy import (
    ArchitecturePolicy,
    EdgeState,
    IgnoredImport,
    ModuleGroup,
    Severity,
    ShadowedPrefix,
    coverage_severity,
    find_shadowed_prefixes,
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


def test_find_shadowed_prefixes_reports_equal_and_descendant_prefixes() -> None:
    """Earlier cross-group prefixes shadow equal and narrower entries."""
    groups = (
        ModuleGroup("inbound_adapter", ("sample.api",), ("inbound_adapter",)),
        ModuleGroup(
            "composition_root",
            ("sample.api.runtime", "sample.api"),
            ("composition_root",),
        ),
    )

    assert find_shadowed_prefixes(groups) == (
        ShadowedPrefix(
            shadowed_group="composition_root",
            shadowed_prefix="sample.api.runtime",
            winning_group="inbound_adapter",
            winning_prefix="sample.api",
        ),
        ShadowedPrefix(
            shadowed_group="composition_root",
            shadowed_prefix="sample.api",
            winning_group="inbound_adapter",
            winning_prefix="sample.api",
        ),
    )


def test_find_shadowed_prefixes_respects_dotted_boundaries() -> None:
    """Lookalike and sibling prefixes do not shadow one another."""
    groups = (
        ModuleGroup(
            "api",
            ("sample.api", "sample.canonical.ingestion"),
            ("api",),
        ),
        ModuleGroup(
            "siblings",
            ("sample.apis", "sample.api_extra", "sample.canonical.ingestion_ports"),
            ("siblings",),
        ),
    )

    assert not find_shadowed_prefixes(groups)


def test_find_shadowed_prefixes_accepts_narrow_before_broad_order() -> None:
    """A specific exception remains reachable before its broader group."""
    groups = (
        ModuleGroup("composition_root", ("sample.api.runtime",), ("root",)),
        ModuleGroup("inbound_adapter", ("sample.api",), ("adapter",)),
    )

    assert not find_shadowed_prefixes(groups)
    assert first_matching_group("sample.api.runtime", groups) == groups[0]


def test_find_shadowed_prefixes_ignores_same_group_redundancy() -> None:
    """Redundant prefixes within one group remain valid policy."""
    groups = (ModuleGroup("domain", ("sample", "sample.domain"), ("domain",)),)

    assert not find_shadowed_prefixes(groups)


def test_find_shadowed_prefixes_uses_first_containing_prefix_in_order() -> None:
    """Records follow later-prefix order and the earliest winning prefix."""
    groups = (
        ModuleGroup("broad", ("sample", "sample.api"), ("broad",)),
        ModuleGroup("intermediate", ("sample.api.runtime",), ("intermediate",)),
        ModuleGroup(
            "later",
            ("sample.api.handlers", "sample.api.jobs"),
            ("later",),
        ),
    )

    assert find_shadowed_prefixes(groups) == (
        ShadowedPrefix(
            shadowed_group="intermediate",
            shadowed_prefix="sample.api.runtime",
            winning_group="broad",
            winning_prefix="sample",
        ),
        ShadowedPrefix(
            shadowed_group="later",
            shadowed_prefix="sample.api.handlers",
            winning_group="broad",
            winning_prefix="sample",
        ),
        ShadowedPrefix(
            shadowed_group="later",
            shadowed_prefix="sample.api.jobs",
            winning_group="broad",
            winning_prefix="sample",
        ),
    )


def test_find_shadowed_prefixes_does_not_cross_package_roots() -> None:
    """Independent package roots do not shadow, while beta ordering does."""
    groups = (
        ModuleGroup("alpha", ("alpha.api",), ("alpha",)),
        ModuleGroup("beta", ("beta.api",), ("beta",)),
        ModuleGroup("beta_exception", ("beta.api.runtime",), ("beta_exception",)),
    )

    assert find_shadowed_prefixes(groups) == (
        ShadowedPrefix(
            shadowed_group="beta_exception",
            shadowed_prefix="beta.api.runtime",
            winning_group="beta",
            winning_prefix="beta.api",
        ),
    )


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
