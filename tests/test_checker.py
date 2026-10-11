"""Unit tests for checker orchestration rules."""

from __future__ import annotations

import textwrap
from pathlib import Path

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import (
    ArchitecturePolicy,
    EdgeState,
    IgnoredImport,
    ModuleGroup,
    Severity,
)

_SAMPLE_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain", "api")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application", "adapter")),
)

#: An ``api`` barrel that re-exports a forbidden symbol but hides it from
#: wildcards, which is exactly the case ``__all__`` must not be able to mask.
_REEXPORT_HIDDEN_FROM_WILDCARDS = (
    "from ..adapters.database import Database\n__all__ = []\n"
)

#: The same barrel with the re-export advertised to wildcard consumers.
_REEXPORT_EXPOSED_TO_WILDCARDS = (
    "from ..adapters.database import Database\n__all__ = ['Database']\n"
)

_STRICT_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application")),
)

#: The same groups with ``application -> adapter`` downgraded to a warning, so
#: the one edge between them is reported without failing.
_WARN_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup(
        "application",
        ("pkg.application",),
        ("application", "domain"),
        ("adapter",),
    ),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
)

#: A package where ``application`` imports ``adapters``, the edge the warning
#: groups above tolerate.
_WARNED_EDGE_FILES = {
    "__init__.py": "",
    "domain/__init__.py": "",
    "application/__init__.py": "",
    "application/service.py": "from pkg.adapters.database import Database\n",
    "adapters/__init__.py": "",
    "adapters/database.py": "class Database: ...\n",
}


def _warned_edge_result(
    root: Path,
    *,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Check the shared warned-edge package against a supplied policy."""
    return _check(root, _WARNED_EDGE_FILES, policy=policy)


def _build_package(root: Path, files: dict[str, str]) -> None:
    """Write a scratch package tree from relative paths to source text."""
    for relative_path, contents in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")


def _policy(
    *,
    groups: tuple[ModuleGroup, ...] = _SAMPLE_GROUPS,
    strict: bool = False,
    ignores: tuple[IgnoredImport, ...] = (),
    include_external_packages: bool = False,
) -> ArchitecturePolicy:
    """Return a policy built from the fixtures' usual knobs."""
    return ArchitecturePolicy(
        groups=groups,
        ignores=ignores,
        strict=strict,
        include_external_packages=include_external_packages,
    )


def _check(
    root: Path,
    files: dict[str, str],
    *,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Build a package, check it, and return the result."""
    package_root = root / "pkg"
    _build_package(package_root, files)
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=policy if policy is not None else _policy(),
    )
    return check_architecture(config)


def _check_api_consumer(
    root: Path,
    *,
    barrel: str,
    consumer: str,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Check ``pkg.api`` re-export semantics for one consumer statement.

    Each re-export scenario differs only in the barrel's ``__all__`` and in how
    the consumer reaches through it, so the package tree lives here and each
    test supplies just those two strings. The ``api`` group may import the
    adapter group, which is what makes a leaked re-export a violation.
    """
    return _check(
        root,
        {
            "__init__.py": "",
            "api/__init__.py": barrel,
            "api/routes.py": "",
            "application/__init__.py": "",
            "application/service.py": consumer,
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
            "domain/__init__.py": "",
        },
        policy=policy,
    )


def test_explicit_import_keeps_origin_when_all_omits_it(tmp_path: Path) -> None:
    """An explicitly imported re-export stays forbidden despite ``__all__ = []``."""
    result = _check_api_consumer(
        tmp_path,
        barrel=_REEXPORT_HIDDEN_FROM_WILDCARDS,
        consumer="from pkg.api import Database\n",
    )

    imported = {violation.imported for violation in result.violations}
    assert not result.ok, f"expected a violation, got {result!r}"
    assert "pkg.adapters.database.Database" in imported, (
        f"expected the re-export origin to be flagged, got {imported!r}"
    )


def test_wildcard_consumer_expands_to_symbol_origins(tmp_path: Path) -> None:
    """A wildcard consumer inherits the origins its export set provides."""
    result = _check_api_consumer(
        tmp_path,
        barrel=_REEXPORT_EXPOSED_TO_WILDCARDS,
        consumer="from pkg.api import *\n",
    )

    imported = {violation.imported for violation in result.violations}
    assert "pkg.adapters.database.Database" in imported, (
        f"wildcard consumer hid a forbidden dependency, got {imported!r}"
    )


def test_wildcard_over_empty_all_binds_no_symbols(tmp_path: Path) -> None:
    """A wildcard over ``__all__ = []`` contributes only the module edge."""
    result = _check_api_consumer(
        tmp_path,
        barrel=_REEXPORT_HIDDEN_FROM_WILDCARDS,
        consumer="from pkg.api import *\n",
    )

    consumer_imports = {
        violation.imported
        for violation in result.violations
        if violation.importer == "pkg.application.service"
    }
    assert "pkg.adapters.database.Database" not in consumer_imports, (
        f"an empty __all__ must not export symbols to a wildcard, "
        f"got {consumer_imports!r}"
    )


def test_unclassified_internal_subtree_is_reported_not_skipped(tmp_path: Path) -> None:
    """A subtree matching no group is surfaced as unclassified coverage."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.newthing import helper\n",
            "newthing/__init__.py": "",
            "newthing/helper.py": "",
        },
    )

    assert result.ok, f"non-strict mode should not fail, got {result!r}"
    states = {diagnostic.state for diagnostic in result.coverage}
    assert EdgeState.UNCLASSIFIED in states, (
        f"expected an unclassified coverage entry, got {result.coverage!r}"
    )


def test_strict_mode_fails_on_unclassified_internal_edge(tmp_path: Path) -> None:
    """Strict mode turns an unclassified internal edge into a failure."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.newthing import helper\n",
            "newthing/__init__.py": "",
            "newthing/helper.py": "",
        },
        policy=_policy(strict=True),
    )

    assert not result.ok, f"strict mode must fail an unclassified edge, got {result!r}"
    assert result.coverage_failures, (
        f"expected coverage failures in strict mode, got {result!r}"
    )


def test_strict_mode_reports_unresolved_internal_distinctly(tmp_path: Path) -> None:
    """An internal symbol no module binds is unresolved, not permitted."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.domain import missing_symbol\n",
        },
        policy=_policy(strict=True),
    )

    assert not result.ok, f"strict mode must fail an unresolved edge, got {result!r}"
    states = {diagnostic.state for diagnostic in result.coverage}
    assert EdgeState.UNRESOLVED in states, (
        f"expected an unresolved coverage entry, got {result.coverage!r}"
    )


def test_unresolved_internal_can_be_downgraded_by_configuration(
    tmp_path: Path,
) -> None:
    """The unresolved-internal severity is configurable as the issue requires."""
    package_root = tmp_path / "pkg"
    _build_package(
        package_root,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.domain import missing_symbol\n",
        },
    )
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=ArchitecturePolicy(
            groups=_STRICT_GROUPS,
            strict=True,
            unresolved_internal_severity=Severity.WARNING,
        ),
    )

    result = check_architecture(config)

    assert result.ok, f"a warning severity must not fail the check, got {result!r}"
    assert result.coverage, f"expected the edge to still be reported, got {result!r}"


def test_documented_ignore_still_exempts_and_stays_distinguishable(
    tmp_path: Path,
) -> None:
    """A configured ignore exempts an edge and is reported as such."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.adapters.database import Database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
        },
        policy=_policy(
            groups=_STRICT_GROUPS,
            strict=True,
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.adapters",
                    reason="Legacy wiring pending migration.",
                ),
            ),
        ),
    )

    assert result.ok, f"a documented ignore must suppress the violation, got {result!r}"
    assert result.ignored, f"expected the exemption to be reported, got {result!r}"
    assert not result.coverage, (
        f"an exempted edge must not also appear as coverage, got {result.coverage!r}"
    )
    assert not result.violations, (
        f"an exempted edge must not appear as a violation, got {result.violations!r}"
    )


def test_documented_ignore_exempts_unclassified_edge_in_strict_mode(
    tmp_path: Path,
) -> None:
    """A documented ignore suppresses an unclassified edge, not just a forbidden one.

    Adopting strict mode surfaces edges that were previously unexamined, and an
    adopter needs the documented-ignore escape hatch for those too. An exemption
    that only covered forbidden edges would leave no way to accept a known
    unclassified edge while the policy is being tightened.

    ``domain/model.py`` exists, so the import resolves: the only reason this
    edge is reportable is that the consumer matches no group, which is the
    unclassified case under test rather than an unresolved one.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "domain/model.py": "",
            "consumer.py": "from pkg.domain import model\n",
        },
        policy=_policy(
            groups=(ModuleGroup("domain", ("pkg.domain",), ("domain",)),),
            strict=True,
            ignores=(
                IgnoredImport(
                    importer="pkg.consumer",
                    imported="pkg.domain",
                    reason="Consumer sits outside the declared groups.",
                ),
            ),
        ),
    )

    assert result.ok, f"a documented ignore must exempt in strict mode, got {result!r}"
    assert result.ignored, f"expected the exemption to be reported, got {result!r}"
    assert not result.coverage_failures, (
        f"an exempted edge must not fail the check, got {result.coverage!r}"
    )
    assert not result.unmatched_ignores, (
        "the ignore applied, so it must not read as stale: "
        f"{result.unmatched_ignores!r}"
    )


def test_documented_ignore_exempts_unresolved_edge_in_strict_mode(
    tmp_path: Path,
) -> None:
    """The exemption also covers an unresolved internal edge."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.gone import helper\n",
        },
        policy=_policy(
            strict=True,
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.gone",
                    reason="Legacy shim pending removal.",
                ),
            ),
        ),
    )

    assert result.ok, f"a documented ignore must exempt in strict mode, got {result!r}"
    assert result.ignored, f"expected the exemption to be reported, got {result!r}"


def test_warning_target_reports_without_failing(tmp_path: Path) -> None:
    """A warned edge is reported, but does not fail the check by default."""
    result = _warned_edge_result(tmp_path, policy=_policy(groups=_WARN_GROUPS))

    assert result.ok, f"a warned edge must not fail the check, got {result!r}"
    assert not result.violations, (
        f"a warned edge must not be a violation, got {result.violations!r}"
    )
    assert not result.coverage, (
        f"a warned edge is classified, so it must not be coverage: {result.coverage!r}"
    )
    # A ``from X import Y`` statement contributes both the module edge and the
    # symbol edge, exactly as it does on the violation path.
    assert {warning.imported for warning in result.warnings} == {
        "pkg.adapters.database",
        "pkg.adapters.database.Database",
    }, f"expected both expanded edges to be warned, got {result.warnings!r}"
    for warning in result.warnings:
        assert warning.importer == "pkg.application.service", (
            f"expected the consumer as importer, got {warning.importer!r}"
        )
        assert (warning.importer_group, warning.imported_group) == (
            "application",
            "adapter",
        ), f"expected both groups on the warning, got {warning!r}"


def test_warning_identities_are_sorted_and_deduplicated(tmp_path: Path) -> None:
    """Warnings are de-duplicated and ordered by their identity.

    The package writes the same import twice, which reaches the checker as two
    edges. Without identity-keyed accumulation the report would carry both and
    its order would depend on traversal, so the assertion pins both halves.
    """
    files = dict(_WARNED_EDGE_FILES)
    files["application/service.py"] = (
        "from pkg.adapters.database import Database\n"
        "from pkg.adapters.database import Database\n"
    )
    result = _check(tmp_path, files, policy=_policy(groups=_WARN_GROUPS))

    identities = [warning.identity() for warning in result.warnings]

    assert identities == sorted(identities), (
        f"warnings must be sorted by identity, got {identities!r}"
    )
    assert len(identities) == len(set(identities)), (
        f"duplicate imports must collapse to one warning, got {identities!r}"
    )


def test_matching_ignore_suppresses_a_warned_edge(tmp_path: Path) -> None:
    """A documented ignore wins over a warning target and counts as matched."""
    result = _warned_edge_result(
        tmp_path,
        policy=_policy(
            groups=_WARN_GROUPS,
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.adapters",
                    reason="Tolerated temporarily, superseded by an ignore.",
                ),
            ),
        ),
    )

    assert not result.warnings, (
        f"an ignore must suppress the warning, got {result.warnings!r}"
    )
    assert result.ignored, f"expected the suppression to be reported, got {result!r}"
    assert not result.unmatched_ignores, (
        f"the ignore applied, so it must not read as stale: {result.unmatched_ignores!r}"
    )


def test_precedence_allows_before_ignores_and_warns(tmp_path: Path) -> None:
    """One run exercises the whole precedence order at once.

    ``application`` allows ``adapter`` and warns ``legacy``, and the package
    imports both. The allowed edge is silent, the ignore aimed at it stays
    unmatched because allowed edges return before the ignore is consulted
    (which is what keeps a stale ignore detectable), and the warned edge is
    reported without failing -- all from a policy that carries warning targets,
    so an ordering mistake would surface here rather than only in isolation.
    """
    precedence_groups = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain", "adapter"),
            ("legacy",),
        ),
        ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
        ModuleGroup("legacy", ("pkg.legacy",), ("legacy",)),
    )
    files = dict(_WARNED_EDGE_FILES)
    files["legacy/__init__.py"] = ""
    files["legacy/old.py"] = ""
    files["application/service.py"] = (
        "from pkg.adapters.database import Database\nimport pkg.legacy.old\n"
    )
    result = _check(
        tmp_path,
        files,
        policy=_policy(
            groups=precedence_groups,
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.adapters",
                    reason="Applied to an edge that is allowed.",
                ),
            ),
        ),
    )

    assert result.ok, f"neither a warning nor a stale ignore may fail, got {result!r}"
    assert {warning.imported for warning in result.warnings} == {"pkg.legacy.old"}, (
        f"only the warned edge is reported, got {result.warnings!r}"
    )
    assert not result.ignored, (
        f"an allowed edge must not be exempted, got {result.ignored!r}"
    )
    assert result.unmatched_ignores == ("pkg.application -> pkg.adapters",), (
        f"an ignore on an allowed edge must read as stale, got {result!r}"
    )


def test_warning_target_does_not_hide_a_forbidden_edge(tmp_path: Path) -> None:
    """A group that warns one target still forbids its other targets.

    Warning support must not widen the allow-list, so the ``domain`` group's
    import of the adapter stays a violation while ``application``'s becomes a
    warning. Both are checked in one run so the two paths are contrasted.
    """
    files = dict(_WARNED_EDGE_FILES)
    files["domain/model.py"] = "from pkg.adapters.database import Database\n"
    result = _check(tmp_path, files, policy=_policy(groups=_WARN_GROUPS))

    forbidden = {violation.importer for violation in result.violations}
    warned = {warning.importer for warning in result.warnings}

    assert forbidden == {"pkg.domain.model"}, (
        f"domain importing the adapter must stay forbidden, got {forbidden!r}"
    )
    assert warned == {"pkg.application.service"}, (
        f"only the warned edge may pass through, got {warned!r}"
    )
    assert not result.ok, f"a real violation must still fail the check, got {result!r}"


def test_direct_warning_edge_is_reported(tmp_path: Path) -> None:
    """A direct ``import`` statement is warned on just like a ``from`` import."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "import pkg.adapters.database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "",
        },
        policy=_policy(groups=_WARN_GROUPS),
    )

    imported = {warning.imported for warning in result.warnings}
    assert "pkg.adapters.database" in imported, (
        f"a direct import must reach the warning path, got {imported!r}"
    )


def test_reexport_through_a_barrel_reaches_a_warning_target(tmp_path: Path) -> None:
    """Each expanded re-export target is classified, including warning ones.

    The consumer imports a symbol a barrel re-exports from the adapter group,
    so the edge reaching policy is the origin rather than the barrel. Warnings
    must appear on that same origin, or a re-export would escape the warning
    exactly as it would otherwise escape a violation.
    """
    # ``application`` warns the adapter group because the re-export hands it an
    # adapter origin, and allows the barrel so the consumer's own module edge is
    # not a violation that would mask the warning under test.
    api_warns_adapter = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain", "api"),
            ("adapter",),
        ),
        ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
        ModuleGroup(
            "api", ("pkg.api",), ("api", "domain", "application"), ("adapter",)
        ),
    )
    result = _check_api_consumer(
        tmp_path,
        barrel=_REEXPORT_HIDDEN_FROM_WILDCARDS,
        consumer="from pkg.api import Database\n",
        policy=_policy(groups=api_warns_adapter),
    )

    assert result.ok, f"a warned re-export must not fail, got {result!r}"
    warned_edges = {
        (warning.importer, warning.imported) for warning in result.warnings
    }
    assert ("pkg.api", "pkg.adapters.database.Database") in warned_edges, (
        f"the barrel's own re-export must be warned, got {warned_edges!r}"
    )
    assert ("pkg.application.service", "pkg.adapters.database.Database") in (
        warned_edges
    ), f"the consumer reaching the origin must be warned, got {warned_edges!r}"
