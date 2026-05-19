"""Architecture checking orchestration."""

from __future__ import annotations

import dataclasses as dc

from .config import HecateConfig, PackageRoot
from .diagnostics import ArchitectureViolation, IgnoredImportDiagnostic
from .imports import ImportReference, collect_imports
from .policy import ArchitecturePolicy
from .reexports import ReexportIndex, build_reexport_index


@dc.dataclass(frozen=True, slots=True)
class ArchitectureCheckResult:
    """Result from checking configured package roots."""

    violations: tuple[ArchitectureViolation, ...]
    ignored: tuple[IgnoredImportDiagnostic, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Return ``True`` when no architecture violations were found."""
        return not self.violations


@dc.dataclass
class _CheckContext:
    """Mutable accumulator passed through the checking traversal."""

    policy: ArchitecturePolicy
    package_names: tuple[str, ...]
    reexports: ReexportIndex
    violations: dict[tuple[str, str, str, int], ArchitectureViolation] = dc.field(
        default_factory=dict
    )
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic] = dc.field(
        default_factory=dict
    )


def check_architecture(config: HecateConfig) -> ArchitectureCheckResult:
    """Check every package root declared in ``config``."""
    ctx = _CheckContext(
        policy=config.policy,
        package_names=tuple(item.name for item in config.packages),
        reexports=build_reexport_index(config.packages),
    )
    for package_root in config.packages:
        _collect_package_violations(package_root, ctx)
    unmatched_ignores = _find_unmatched_ignores(config.policy, ctx.ignored)
    return ArchitectureCheckResult(
        violations=tuple(
            sorted(ctx.violations.values(), key=lambda item: item.identity())
        ),
        ignored=tuple(sorted(ctx.ignored.values(), key=lambda item: item.render())),
        unmatched_ignores=unmatched_ignores,
    )


def _collect_package_violations(
    package_root: PackageRoot,
    ctx: _CheckContext,
) -> None:
    for source_path in sorted(package_root.root.rglob("*.py")):
        for import_reference in collect_imports(
            source_path, root=package_root.root, package=package_root.name
        ):
            for imported in ctx.reexports.expand_import(import_reference.imported):
                _record_import_edge(import_reference, imported=imported, ctx=ctx)


def _record_import_edge(
    import_reference: ImportReference,
    *,
    imported: str,
    ctx: _CheckContext,
) -> None:
    if not ctx.policy.include_external_packages and not _is_internal_module(
        imported, ctx.package_names
    ):
        return
    importer_group = ctx.policy.group_for(import_reference.importer)
    imported_group = ctx.policy.group_for(imported)
    if importer_group is None or imported_group is None:
        return
    if ctx.policy.is_allowed(importer_group.name, imported_group.name):
        return
    ignored_import = ctx.policy.ignored_import_for(import_reference.importer, imported)
    if ignored_import is not None:
        ctx.ignored[import_reference.importer, imported] = IgnoredImportDiagnostic(
            importer=import_reference.importer,
            imported=imported,
            reason=ignored_import.reason,
        )
        return
    violation = ArchitectureViolation(
        rule_id=ctx.policy.default_rule_id,
        importer=import_reference.importer,
        imported=imported,
        importer_group=importer_group.name,
        imported_group=imported_group.name,
        source_path=import_reference.source_path,
        line=import_reference.line,
    )
    ctx.violations[violation.identity()] = violation


def _is_internal_module(module: str, package_names: tuple[str, ...]) -> bool:
    return any(
        module == package or module.startswith(f"{package}.")
        for package in package_names
    )


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
