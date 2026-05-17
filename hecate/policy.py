"""Architecture policy classification and allowance rules."""

from __future__ import annotations

import dataclasses as dc

from .imports import is_module_prefix


@dc.dataclass(frozen=True, slots=True)
class ModuleGroup:
    """A named architecture group matched by ordered dotted prefixes."""

    name: str
    prefixes: tuple[str, ...]
    allowed: tuple[str, ...]


@dc.dataclass(frozen=True, slots=True)
class IgnoredImport:
    """One documented import edge ignored by policy."""

    importer: str
    imported: str
    reason: str


@dc.dataclass(frozen=True, slots=True)
class ArchitecturePolicy:
    """Validated architecture policy used by the checker."""

    groups: tuple[ModuleGroup, ...]
    ignores: tuple[IgnoredImport, ...] = ()
    default_rule_id: str = "HEC001"
    include_external_packages: bool = False

    def group_for(self, module: str) -> ModuleGroup | None:
        """Return the first matching group for ``module``."""
        return first_matching_group(module, self.groups)

    def is_allowed(self, importer_group: str, imported_group: str) -> bool:
        """Return whether one classified group may import another."""
        return is_group_allowed(importer_group, imported_group, self.groups)

    def ignored_import_for(self, importer: str, imported: str) -> IgnoredImport | None:
        """Return the matching ignore for one import edge, if present."""
        for ignored_import in self.ignores:
            if ignore_matches(ignored_import, importer, imported):
                return ignored_import
        return None


def first_matching_group(
    module: str, groups: tuple[ModuleGroup, ...]
) -> ModuleGroup | None:
    """Return the first configured group that contains ``module``."""
    assert module
    for group in groups:
        if any(is_module_prefix(prefix, module) for prefix in group.prefixes):
            return group
    return None


def is_group_allowed(
    importer_group: str, imported_group: str, groups: tuple[ModuleGroup, ...]
) -> bool:
    """Return whether ``importer_group`` may import ``imported_group``."""
    assert importer_group
    assert imported_group
    for group in groups:
        if group.name == importer_group:
            return imported_group in group.allowed
    return False


def ignore_matches(ignored_import: IgnoredImport, importer: str, imported: str) -> bool:
    """Return whether an ignore entry covers an import edge."""
    assert importer
    assert imported
    return is_module_prefix(ignored_import.importer, importer) and is_module_prefix(
        ignored_import.imported, imported
    )
