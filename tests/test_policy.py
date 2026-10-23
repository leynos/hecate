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

    shadows = find_shadowed_prefixes(groups)
    assert shadows == (
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
    ), f"expected equal and descendant shadow records, got {shadows!r}"


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

    shadows = find_shadowed_prefixes(groups)
    assert not shadows, f"expected no dotted-boundary shadows, got {shadows!r}"


def test_find_shadowed_prefixes_accepts_narrow_before_broad_order() -> None:
    """A specific exception remains reachable before its broader group."""
    groups = (
        ModuleGroup("composition_root", ("sample.api.runtime",), ("root",)),
        ModuleGroup("inbound_adapter", ("sample.api",), ("adapter",)),
    )

    shadows = find_shadowed_prefixes(groups)
    assert not shadows, f"expected no shadows for narrow-first order, got {shadows!r}"
    matched = first_matching_group("sample.api.runtime", groups)
    assert matched == groups[0], (
        f"expected 'sample.api.runtime' to match {groups[0]!r}, got {matched!r}"
    )


def test_find_shadowed_prefixes_ignores_same_group_redundancy() -> None:
    """Redundant prefixes within one group remain valid policy."""
    groups = (ModuleGroup("domain", ("sample", "sample.domain"), ("domain",)),)

    shadows = find_shadowed_prefixes(groups)
    assert not shadows, f"expected same-group prefixes to remain valid, got {shadows!r}"


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

    shadows = find_shadowed_prefixes(groups)
    assert shadows == (
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
    ), f"expected deterministic earliest-prefix records, got {shadows!r}"


def test_find_shadowed_prefixes_does_not_cross_package_roots() -> None:
    """Independent package roots do not shadow, while beta ordering does."""
    groups = (
        ModuleGroup("alpha", ("alpha.api",), ("alpha",)),
        ModuleGroup("beta", ("beta.api",), ("beta",)),
        ModuleGroup("beta_exception", ("beta.api.runtime",), ("beta_exception",)),
    )

    shadows = find_shadowed_prefixes(groups)
    assert shadows == (
        ShadowedPrefix(
            shadowed_group="beta_exception",
            shadowed_prefix="beta.api.runtime",
            winning_group="beta",
            winning_prefix="beta.api",
        ),
    ), f"expected only beta root shadow record, got {shadows!r}"


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
