"""Architecture checking orchestration."""

from __future__ import annotations

import dataclasses as dc

from .classification import CheckContext, Edge, classify_origin
from .config import HecateConfig
from .diagnostics import (
    ArchitectureViolation,
    ArchitectureWarning,
    CoverageDiagnostic,
    IgnoredImportDiagnostic,
    UnclassifiedModuleDiagnostic,
)
from .imports import (
    DiscoveredModule,
    FromImport,
    ImportStatement,
    collect_import_statements,
    discover_modules,
)
from .module_coverage import collect_unclassified_modules
from .namespaces import analyse_namespaces
from .origins import Resolution, build_origin_index
from .policy import ArchitecturePolicy


@dc.dataclass(frozen=True, slots=True)
class ArchitectureCheckResult:
    """Result from checking configured package roots."""

    violations: tuple[ArchitectureViolation, ...]
    ignored: tuple[IgnoredImportDiagnostic, ...] = ()
    coverage: tuple[CoverageDiagnostic, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()
    unclassified_modules: tuple[UnclassifiedModuleDiagnostic, ...] = ()
    warnings: tuple[ArchitectureWarning, ...] = ()

    @property
    def ok(self) -> bool:
        """Return ``True`` when no architecture violation was found.

        Coverage diagnostics only fail the check when they carry error
        severity, which happens for unclassified and unresolved internal edges
        under strict mode. Unclassified-module diagnostics fail it the same
        way, so a warning-only run stays green, and warning-level edges never
        fail here: they are tolerated by policy, and only
        ``--fail-on-warnings`` acts on them.
        """
        failures = (self.coverage, self.unclassified_modules)
        return not self.violations and not any(
            diagnostic.is_failure
            for diagnostics in failures
            for diagnostic in diagnostics
        )

    @property
    def coverage_failures(self) -> tuple[CoverageDiagnostic, ...]:
        """Return the coverage diagnostics that fail the check."""
        return tuple(
            diagnostic for diagnostic in self.coverage if diagnostic.is_failure
        )


def check_architecture(config: HecateConfig) -> ArchitectureCheckResult:
    """Check every package root declared in ``config``."""
    discoveries = tuple(
        discover_modules(package_root.root, package_root.name)
        for package_root in config.packages
    )
    namespaces = analyse_namespaces(discoveries)
    ctx = CheckContext(
        policy=config.policy,
        origins=build_origin_index(config.packages, namespaces),
    )
    for discovery in discoveries:
        _collect_package_edges(discovery.modules, ctx)
        collect_unclassified_modules(
            discovery.modules, policy=config.policy, report=ctx.unclassified
        )
    unmatched_ignores = _find_unmatched_ignores(config.policy, ctx.ignored)
    return ArchitectureCheckResult(
        violations=tuple(
            sorted(ctx.violations.values(), key=lambda item: item.identity())
        ),
        ignored=tuple(sorted(ctx.ignored.values(), key=lambda item: item.render())),
        coverage=tuple(sorted(ctx.coverage.values(), key=lambda item: item.identity())),
        unmatched_ignores=unmatched_ignores,
        unclassified_modules=tuple(
            sorted(ctx.unclassified.values(), key=lambda item: item.identity())
        ),
        warnings=tuple(
            sorted(ctx.warnings.values(), key=lambda item: item.identity())
        ),
    )


def _collect_package_edges(
    discovered: tuple[DiscoveredModule, ...], ctx: CheckContext
) -> None:
    """Evaluate every import edge in one package root against policy."""
    for source in discovered:
        statements = collect_import_statements(source.source_path, module=source.module)
        for statement in statements:
            _evaluate_statement(statement, ctx=ctx)


def _evaluate_statement(statement: ImportStatement, *, ctx: CheckContext) -> None:
    """Evaluate one import statement, expanding wildcards where knowable.

    A ``from target import name`` statement yields two edges: the target module
    and the symbol reached through it. When the target is unresolvable the
    symbol cannot be reached either, so both edges would report one broken
    import twice. The symbol edge is skipped only when it is unresolved for
    that same reason: a symbol that *does* resolve despite its parent is a real
    dependency, and dropping it would reintroduce the false negatives this
    change exists to remove.
    """
    target_unresolved = _target_unresolved_internal(statement, ctx=ctx)
    if isinstance(statement, FromImport):
        _record_edge(statement, imported=statement.target, ctx=ctx)
    if not any(name == "*" for name in _names_for(statement)):
        # Named and direct imports contribute their own module edges.
        for imported in _named_targets(statement):
            if target_unresolved and _unresolved_internal(imported, ctx=ctx):
                continue
            _record_edge(statement, imported=imported, ctx=ctx)
        return
    _evaluate_wildcard(statement, ctx=ctx)


def _target_unresolved_internal(
    statement: ImportStatement, *, ctx: CheckContext
) -> bool:
    """Return whether a ``from`` statement's target is internally unresolvable."""
    if not isinstance(statement, FromImport):
        return False
    return _unresolved_internal(statement.target, ctx=ctx)


def _unresolved_internal(imported: str, *, ctx: CheckContext) -> bool:
    """Return whether ``imported`` names no known internal module."""
    return ctx.origins.resolve(imported) is Resolution.UNRESOLVED_INTERNAL


def _evaluate_wildcard(statement: ImportStatement, *, ctx: CheckContext) -> None:
    """Evaluate a wildcard import using Python's wildcard semantics.

    Statically knowable exports are expanded into concrete symbol edges. The
    package-level edge was already recorded by :func:`_evaluate_statement`,
    which is what reports an unresolvable export set rather than silently
    approximating it away. Python does not allow naming further imports beside
    a ``*``, so no per-name edges belong here.
    """
    target = _wildcard_target(statement)
    if target is None:
        return
    if ctx.origins.resolve(target) is not Resolution.RESOLVED:
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
    statement: ImportStatement, *, imported: str, ctx: CheckContext
) -> None:
    """Resolve an import target and classify each origin it could reach.

    Every path records exactly one outcome per origin, so an absent diagnostic
    always means the edge was permitted rather than merely unexamined.
    """
    for origin in ctx.origins.origins_for(imported):
        classify_origin(Edge.from_statement(statement, imported=origin), ctx=ctx)


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
