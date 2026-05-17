"""Architecture checking orchestration."""
# pylint: disable=too-many-arguments

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


def check_architecture(config: HecateConfig) -> ArchitectureCheckResult:
    """Check every package root declared in ``config``."""
    violations: dict[tuple[str, str, str, int], ArchitectureViolation] = {}
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic] = {}
    reexports = build_reexport_index(config.packages)
    for package_root in config.packages:
        _collect_package_violations(
            package_root,
            policy=config.policy,
            package_names=tuple(item.name for item in config.packages),
            reexports=reexports,
            violations=violations,
            ignored=ignored,
        )
    unmatched_ignores = _find_unmatched_ignores(config.policy, ignored)
    return ArchitectureCheckResult(
        violations=tuple(sorted(violations.values(), key=lambda item: item.identity())),
        ignored=tuple(sorted(ignored.values(), key=lambda item: item.render())),
        unmatched_ignores=unmatched_ignores,
    )


def _collect_package_violations(
    package_root: PackageRoot,
    *,
    policy: ArchitecturePolicy,
    package_names: tuple[str, ...],
    reexports: ReexportIndex,
    violations: dict[tuple[str, str, str, int], ArchitectureViolation],
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic],
) -> None:
    for source_path in sorted(package_root.root.rglob("*.py")):
        for import_reference in collect_imports(
            source_path, root=package_root.root, package=package_root.name
        ):
            for imported in reexports.expand_import(import_reference.imported):
                _record_import_edge(
                    import_reference,
                    imported=imported,
                    policy=policy,
                    package_names=package_names,
                    violations=violations,
                    ignored=ignored,
                )


def _record_import_edge(
    import_reference: ImportReference,
    *,
    imported: str,
    policy: ArchitecturePolicy,
    package_names: tuple[str, ...],
    violations: dict[tuple[str, str, str, int], ArchitectureViolation],
    ignored: dict[tuple[str, str], IgnoredImportDiagnostic],
) -> None:
    if not policy.include_external_packages and not _is_internal_module(
        imported, package_names
    ):
        return
    importer_group = policy.group_for(import_reference.importer)
    imported_group = policy.group_for(imported)
    if importer_group is None or imported_group is None:
        return
    ignored_import = policy.ignored_import_for(import_reference.importer, imported)
    if ignored_import is not None:
        ignored[import_reference.importer, imported] = IgnoredImportDiagnostic(
            importer=import_reference.importer,
            imported=imported,
            reason=ignored_import.reason,
        )
        return
    if policy.is_allowed(importer_group.name, imported_group.name):
        return
    violation = ArchitectureViolation(
        rule_id=policy.default_rule_id,
        importer=import_reference.importer,
        imported=imported,
        importer_group=importer_group.name,
        imported_group=imported_group.name,
        source_path=import_reference.source_path,
        line=import_reference.line,
    )
    violations[violation.identity()] = violation


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
