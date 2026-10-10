"""Architecture policy classification and allowance rules."""

from __future__ import annotations

import dataclasses as dc
import enum

from .imports import is_module_prefix


class Severity(enum.StrEnum):
    """How a diagnostic affects the overall check result."""

    ERROR = "error"
    """Fails the check and sets a non-zero exit code."""

    WARNING = "warning"
    """Reported but does not fail the check."""

    EXEMPT = "exempt"
    """Deliberately accepted, usually through a configured ignore entry."""


class EdgeState(enum.StrEnum):
    """The outcome of evaluating one import edge against policy."""

    PERMITTED = "permitted"
    """Both endpoints classified, and the importer group may import the target."""

    FORBIDDEN = "forbidden"
    """Both endpoints classified, and the importer group may not import it."""

    EXEMPTED = "exempted"
    """Forbidden in principle, but covered by a documented ignore entry."""

    UNCLASSIFIED = "unclassified"
    """At least one endpoint matched no configured group."""

    UNRESOLVED = "unresolved"
    """The import target could not be resolved to a known module."""


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
    strict: bool = False
    """Whether unclassified and unresolved internal edges fail the check."""

    unresolved_internal_severity: Severity = Severity.ERROR
    """Severity applied to unresolved internal edges under strict mode."""

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
