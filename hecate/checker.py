"""Architecture checking orchestration."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from .config import HecateConfig, PackageRoot
from .diagnostics import (
    ArchitectureViolation,
    CoverageDiagnostic,
    IgnoredImportDiagnostic,
)
from .imports import FromImport, ImportStatement, collect_import_statements
from .namespaces import analyse_namespaces
from .origins import OriginIndex, Resolution, build_origin_index
from .policy import ArchitecturePolicy, EdgeState, ModuleGroup, Severity

if typ.TYPE_CHECKING:
    from pathlib import Path


@dc.dataclass(frozen=True, slots=True)
class ArchitectureCheckResult:
    """Result from checking configured package roots."""

    violations: tuple[ArchitectureViolation, ...]
    ignored: tuple[IgnoredImportDiagnostic, ...] = ()
    coverage: tuple[CoverageDiagnostic, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Return ``True`` when no architecture violation was found.

        Coverage diagnostics only fail the check when they carry error
        severity, which happens for unclassified and unresolved internal edges
        under strict mode.
        """
        return not self.violations and not any(
            diagnostic.is_failure for diagnostic in self.coverage
        )

    @property
    def coverage_failures(self) -> tuple[CoverageDiagnostic, ...]:
        """Return the coverage diagnostics that fail the check."""
        return tuple(
            diagnostic for diagnostic in self.coverage if diagnostic.is_failure
        )


@dc.dataclass(frozen=True, slots=True)
class _Edge:
    """One import edge under evaluation, independent of its statement form.

    Wildcard expansion produces edges that no single statement spells out, so
    classification works from the resolved importer, target, and source site
    rather than from the statement that led here.
    """

    importer: str
    imported: str
    source_path: Path
    line: int

    @classmethod
    def from_statement(cls, statement: ImportStatement, *, imported: str) -> _Edge:
        """Return the edge one statement contributes for ``imported``."""
        return cls(
            importer=statement.importer,
            imported=imported,
            source_path=statement.source_path,
            line=statement.line,
        )


@dc.dataclass
class _CheckContext:
    """Mutable accumulator passed through the checking traversal."""

    policy: ArchitecturePolicy
    origins: OriginIndex
    violations: dict[tuple[str, str, str, int], ArchitectureViolation] = dc.field(
        default_factory=dict
    )
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic] = dc.field(
        default_factory=dict
    )
    coverage: dict[tuple[str, str, str, str, int], CoverageDiagnostic] = dc.field(
        default_factory=dict
    )


def check_architecture(config: HecateConfig) -> ArchitectureCheckResult:
    """Check every package root declared in ``config``."""
    namespaces = analyse_namespaces(config.packages)
    ctx = _CheckContext(
        policy=config.policy,
        origins=build_origin_index(config.packages, namespaces),
    )
    for package_root in config.packages:
        _collect_package_edges(package_root, ctx)
    unmatched_ignores = _find_unmatched_ignores(config.policy, ctx.ignored)
    return ArchitectureCheckResult(
        violations=tuple(
            sorted(ctx.violations.values(), key=lambda item: item.identity())
        ),
        ignored=tuple(sorted(ctx.ignored.values(), key=lambda item: item.render())),
        coverage=tuple(sorted(ctx.coverage.values(), key=lambda item: item.identity())),
        unmatched_ignores=unmatched_ignores,
    )


def _collect_package_edges(package_root: PackageRoot, ctx: _CheckContext) -> None:
    """Evaluate every import edge in one package root against policy."""
    for source_path in sorted(package_root.root.rglob("*.py")):
        statements = collect_import_statements(
            source_path, root=package_root.root, package=package_root.name
        )
        for statement in statements:
            _evaluate_statement(statement, ctx=ctx)


def _evaluate_statement(statement: ImportStatement, *, ctx: _CheckContext) -> None:
    """Evaluate one import statement, expanding wildcards where knowable."""
    if isinstance(statement, FromImport):
        _record_edge(statement, imported=statement.target, ctx=ctx)
    if not any(name == "*" for name in _names_for(statement)):
        # Named and direct imports contribute their own module edges.
        for imported in _named_targets(statement):
            _record_edge(statement, imported=imported, ctx=ctx)
        return
    _evaluate_wildcard(statement, ctx=ctx)


def _evaluate_wildcard(statement: ImportStatement, *, ctx: _CheckContext) -> None:
    """Evaluate a wildcard import using Python's wildcard semantics.

    Statically knowable exports are expanded into concrete symbol edges. The
    package-level edge is recorded in its own right, and an unresolvable export
    set is reported rather than silently approximated away.
    """
    target = _wildcard_target(statement)
    if target is None:
        return
    for name in _named_targets(statement):
        _record_edge(statement, imported=name, ctx=ctx)
    resolution = ctx.origins.resolve(target)
    if resolution is not Resolution.RESOLVED:
        _record_edge(statement, imported=target, ctx=ctx)
        return
    exports = ctx.origins.wildcard_exports(target)
    if not exports:
        # A statically empty selection binds nothing; ``__all__ = []`` is a
        # legitimate, fully-understood declaration.
        return
    for imported in exports:
        _record_edge(statement, imported=imported, ctx=ctx)


def _names_for(statement: ImportStatement) -> tuple[str, ...]:
    return statement.names if isinstance(statement, FromImport) else ()


def _named_targets(statement: ImportStatement) -> tuple[str, ...]:
    """Return the dotted targets a statement imports by name."""
    if isinstance(statement, FromImport):
        return tuple(
            f"{statement.target}.{name}" for name in statement.names if name != "*"
        )
    return (statement.module,)


def _wildcard_target(statement: ImportStatement) -> str | None:
    if isinstance(statement, FromImport) and "*" in statement.names:
        return statement.target
    return None


def _record_edge(
    statement: ImportStatement, *, imported: str, ctx: _CheckContext
) -> None:
    """Resolve an import target and classify each origin it could reach.

    Every path records exactly one outcome per origin, so an absent diagnostic
    always means the edge was permitted rather than merely unexamined.
    """
    for origin in ctx.origins.origins_for(imported):
        _classify_origin(_Edge.from_statement(statement, imported=origin), ctx=ctx)


def _classify_origin(edge: _Edge, *, ctx: _CheckContext) -> None:
    """Classify one already-expanded origin of an import edge."""
    imported = edge.imported
    resolution = ctx.origins.resolve(imported)
    importer_group = ctx.policy.group_for(edge.importer)
    imported_group = ctx.policy.group_for(imported)
    if resolution is Resolution.EXTERNAL and not _policy_claims_external(
        imported_group, ctx=ctx
    ):
        return
    if resolution is Resolution.UNRESOLVED_INTERNAL:
        _record_coverage(
            edge,
            state=EdgeState.UNRESOLVED,
            groups=(importer_group, imported_group),
            ctx=ctx,
        )
        return
    if importer_group is None or imported_group is None:
        _record_coverage(
            edge,
            state=EdgeState.UNCLASSIFIED,
            groups=(importer_group, imported_group),
            ctx=ctx,
        )
        return
    if ctx.policy.is_allowed(importer_group.name, imported_group.name):
        return
    ignored_import = ctx.policy.ignored_import_for(edge.importer, imported)
    if ignored_import is not None:
        ctx.ignored[edge.importer, imported] = IgnoredImportDiagnostic(
            importer=edge.importer,
            imported=imported,
            reason=ignored_import.reason,
        )
        return
    violation = ArchitectureViolation(
        rule_id=ctx.policy.default_rule_id,
        importer=edge.importer,
        imported=imported,
        importer_group=importer_group.name,
        imported_group=imported_group.name,
        source_path=edge.source_path,
        line=edge.line,
    )
    ctx.violations[violation.identity()] = violation


def _record_coverage(
    edge: _Edge,
    *,
    state: EdgeState,
    groups: tuple[ModuleGroup | None, ModuleGroup | None],
    ctx: _CheckContext,
) -> None:
    """Record an unclassified or unresolved edge at policy-determined severity."""
    importer_group, imported_group = groups
    diagnostic = CoverageDiagnostic(
        state=state,
        severity=coverage_severity(state, ctx.policy),
        rule_id=ctx.policy.default_rule_id,
        importer=edge.importer,
        imported=edge.imported,
        source_path=edge.source_path,
        line=edge.line,
        importer_group=importer_group.name if importer_group else None,
        imported_group=imported_group.name if imported_group else None,
    )
    ctx.coverage[diagnostic.identity()] = diagnostic


def _policy_claims_external(
    imported_group: ModuleGroup | None, *, ctx: _CheckContext
) -> bool:
    """Return whether the policy takes a position on an external dependency.

    ``include_external_packages`` widens what *can* be classified; it does not
    assert that every third-party import was classified. So an external edge is
    in scope only when the option is enabled *and* a configured group claims
    its prefix. Anything else is a dependency the policy never expressed an
    opinion about, and is skipped rather than reported: otherwise every stdlib
    import would become an unclassified failure once strict mode meets
    external packages.
    """
    if not ctx.policy.include_external_packages:
        return False
    return imported_group is not None


def coverage_severity(state: EdgeState, policy: ArchitecturePolicy) -> Severity:
    """Return the severity to apply to one coverage state.

    Outside strict mode these states are reported as warnings so that a green
    result can be tightened into a failing one without a second code path. In
    strict mode unclassified internal edges always fail, and unresolved
    internal edges use the configured severity.
    """
    if not policy.strict:
        return Severity.WARNING
    if state is EdgeState.UNRESOLVED:
        return policy.unresolved_internal_severity
    return Severity.ERROR


def _find_unmatched_ignores(
    policy: ArchitecturePolicy,
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic],
) -> tuple[str, ...]:
    matched = set(ignored)
    unmatched = [
        f"{ignored_import.importer} -> {ignored_import.imported}"
        for ignored_import in policy.ignores
        if not any(
            policy.ignored_import_for(importer, imported) == ignored_import
            for importer, imported in matched
        )
    ]
    return tuple(sorted(unmatched))
