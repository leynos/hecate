"""Architecture policy classification and allowance rules."""

from __future__ import annotations

import dataclasses as dc

from .imports import is_module_prefix


def module_prefix_contains(prefix: str, module: str) -> bool:
    """Return whether a dotted prefix contains a module."""
    assert prefix
    assert module
    return is_module_prefix(prefix, module)


def group_allowed_by_list(imported_group: str, allowed: tuple[str, ...]) -> bool:
    """Return whether ``imported_group`` appears in a configured allow-list."""
    assert imported_group
    return imported_group in allowed


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
    for group in groups:
        if any(module_prefix_contains(prefix, module) for prefix in group.prefixes):
            return group
    return None


def is_group_allowed(
    importer_group: str, imported_group: str, groups: tuple[ModuleGroup, ...]
) -> bool:
    """Return whether ``importer_group`` may import ``imported_group``."""
    for group in groups:
        if group.name == importer_group:
            return group_allowed_by_list(imported_group, group.allowed)
    return False


def ignore_matches(ignored_import: IgnoredImport, importer: str, imported: str) -> bool:
    """Return whether an ignore entry covers an import edge."""
    return module_prefix_contains(
        ignored_import.importer, importer
    ) and module_prefix_contains(ignored_import.imported, imported)
