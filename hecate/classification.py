"""Edge classification against the architecture policy.

Traversal lives in ``checker``; deciding what one resolved edge *means* lives
here. The split keeps the precedence order — the observable contract of the
policy model — in one small module, so it can be read and changed without
following the filesystem walk that produced the edge.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from .diagnostics import (
    ArchitectureViolation,
    ArchitectureWarning,
    CoverageDiagnostic,
    IgnoredImportDiagnostic,
    UnclassifiedModuleDiagnostic,
)
from .origins import OriginIndex, Resolution
from .policy import (
    ArchitecturePolicy,
    EdgeState,
    ModuleGroup,
    coverage_severity,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from .imports import ImportStatement


@dc.dataclass(frozen=True, slots=True)
class Edge:
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
    def from_statement(cls, statement: ImportStatement, *, imported: str) -> Edge:
        """Return the edge one statement contributes for ``imported``."""
        return cls(
            importer=statement.importer,
            imported=imported,
            source_path=statement.source_path,
            line=statement.line,
        )


@dc.dataclass
class CheckContext:
    """Mutable accumulator passed through the checking traversal."""

    policy: ArchitecturePolicy
    origins: OriginIndex
    violations: dict[tuple[str, str, str, int], ArchitectureViolation] = dc.field(
        default_factory=dict
    )
    warnings: dict[tuple[str, str, str, int], ArchitectureWarning] = dc.field(
        default_factory=dict
    )
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic] = dc.field(
        default_factory=dict
    )
    coverage: dict[tuple[str, str, str, str, int], CoverageDiagnostic] = dc.field(
        default_factory=dict
    )
    unclassified: dict[str, UnclassifiedModuleDiagnostic] = dc.field(
        default_factory=dict
    )


def classify_origin(edge: Edge, *, ctx: CheckContext) -> None:
    """Classify one already-expanded origin of an import edge.

    Precedence is fixed so an edge's outcome never depends on evaluation order
    further up the pipeline. An edge whose endpoints cannot both be classified
    is skipped or recorded as coverage and never reaches the policy at all. Of
    the rest, an allowed target is silent, a documented ignore is honoured
    next, a warning-level target is reported without failing, and only what
    remains is forbidden.
    """
    endpoints = _classified_endpoints(edge, ctx=ctx)
    if endpoints is None:
        return
    importer_group, imported_group = endpoints
    if ctx.policy.is_allowed(importer_group.name, imported_group.name):
        return
    if _record_exemption(edge, ctx=ctx):
        return
    _record_classified_outcome(
        edge, importer_group=importer_group, imported_group=imported_group, ctx=ctx
    )


def _classified_endpoints(
    edge: Edge, *, ctx: CheckContext
) -> tuple[ModuleGroup, ModuleGroup] | None:
    """Resolve both endpoints, recording coverage when either is unusable.

    Returns ``None`` when the edge is out of scope or was recorded as coverage,
    so the caller only sees edges the policy can decide. A documented ignore is
    honoured after this point rather than here, which is what makes an edge the
    policy could not classify or resolve exemptible just like a forbidden one.
    """
    imported = edge.imported
    resolution = ctx.origins.resolve(imported)
    importer_group = ctx.policy.group_for(edge.importer)
    imported_group = ctx.policy.group_for(imported)
    if resolution is Resolution.EXTERNAL and not _policy_claims_external(
        imported_group, ctx=ctx
    ):
        return None
    if resolution is Resolution.UNRESOLVED_INTERNAL:
        _exempt_or_record_coverage(
            edge,
            state=EdgeState.UNRESOLVED,
            groups=(importer_group, imported_group),
            ctx=ctx,
        )
        return None
    if importer_group is None or imported_group is None:
        _exempt_or_record_coverage(
            edge,
            state=EdgeState.UNCLASSIFIED,
            groups=(importer_group, imported_group),
            ctx=ctx,
        )
        return None
    return importer_group, imported_group


def _record_classified_outcome(
    edge: Edge,
    *,
    importer_group: ModuleGroup,
    imported_group: ModuleGroup,
    ctx: CheckContext,
) -> None:
    """Record a classified edge as a warning, or else as a violation."""
    if ctx.policy.is_warned(importer_group.name, imported_group.name):
        _record_warning(
            edge, importer_group=importer_group, imported_group=imported_group, ctx=ctx
        )
        return
    violation = ArchitectureViolation(
        rule_id=ctx.policy.default_rule_id,
        importer=edge.importer,
        imported=edge.imported,
        importer_group=importer_group.name,
        imported_group=imported_group.name,
        source_path=edge.source_path,
        line=edge.line,
    )
    ctx.violations[violation.identity()] = violation


def _record_warning(
    edge: Edge,
    *,
    importer_group: ModuleGroup,
    imported_group: ModuleGroup,
    ctx: CheckContext,
) -> None:
    """Record a tolerated edge the policy wants kept visible."""
    warning = ArchitectureWarning(
        rule_id=ctx.policy.default_rule_id,
        importer=edge.importer,
        imported=edge.imported,
        importer_group=importer_group.name,
        imported_group=imported_group.name,
        source_path=edge.source_path,
        line=edge.line,
    )
    ctx.warnings[warning.identity()] = warning


def _exempt_or_record_coverage(
    edge: Edge,
    *,
    state: EdgeState,
    groups: tuple[ModuleGroup | None, ModuleGroup | None],
    ctx: CheckContext,
) -> None:
    """Honour a documented ignore for an incomplete edge, else report it."""
    if not _record_exemption(edge, ctx=ctx):
        _record_coverage(edge, state=state, groups=groups, ctx=ctx)


def _record_exemption(edge: Edge, *, ctx: CheckContext) -> bool:
    """Record a documented ignore covering ``edge``, if one exists.

    Any non-permitted outcome is exemptible, so an edge the policy could not
    classify or resolve can be suppressed under a documented reason just like a
    forbidden one. The exemption is recorded so that it stays visible and so a
    fail-on-unmatched-ignore run can still tell the entry applied.
    """
    ignored_import = ctx.policy.ignored_import_for(edge.importer, edge.imported)
    if ignored_import is None:
        return False
    ctx.ignored[edge.importer, edge.imported] = IgnoredImportDiagnostic(
        importer=edge.importer,
        imported=edge.imported,
        reason=ignored_import.reason,
    )
    return True


def _record_coverage(
    edge: Edge,
    *,
    state: EdgeState,
    groups: tuple[ModuleGroup | None, ModuleGroup | None],
    ctx: CheckContext,
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
    imported_group: ModuleGroup | None, *, ctx: CheckContext
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
