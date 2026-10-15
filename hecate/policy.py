"""Architecture policy classification and allowance rules."""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

from .imports import is_module_prefix

UnclassifiedModules = typ.Literal["ignore", "warn", "error"]
"""How an internal module no configured group classifies is reported."""

UNCLASSIFIED_MODULE_MODES: tuple[str, ...] = typ.get_args(UnclassifiedModules)
"""Permitted :data:`UnclassifiedModules` values, in the order the literal spells.

Derived from the literal rather than written out a second time, so the type a
reader sees and the set the configuration validator accepts cannot drift apart.
"""


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
class ShadowedPrefix:
    """A group prefix that an earlier group prefix makes unreachable."""

    shadowed_group: str
    shadowed_prefix: str
    winning_group: str
    winning_prefix: str


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

    unclassified_modules: UnclassifiedModules = "ignore"
    """How a discovered module no configured group classifies is reported.

    ``ignore`` preserves the historical behaviour of saying nothing about a
    module no group claims. ``warn`` and ``error`` make the policy's coverage
    gap visible by naming each such module rather than waiting for an import
    edge to expose it.
    """

    def group_for(self, module: str) -> ModuleGroup | None:
        """Return the first matching group for ``module``."""
        return first_matching_group(module, self.groups)

    def claims_module(self, module: str, *, is_package_init: bool = False) -> bool:
        """Return whether ``module`` falls inside the scope of some group.

        This answers the module-coverage question, not the edge question. A
        package initializer is claimed when any of its own submodules is: an
        initializer imports and re-exports what its submodules bind, so a
        policy that governs ``pkg.domain`` already governs the package
        ``pkg.domain`` itself. Without this, every conventional package would
        need an extra recursive group for its root, and that group would in
        turn claim every future subpackage the module pass exists to find.

        A plain module is claimed only through its own containing prefix, so a
        new ``pkg.newfeature`` stays unclassified even when ``pkg`` itself is an
        initializer some sibling group covers.
        """
        if self.group_for(module) is not None:
            return True
        if not is_package_init:
            return False
        return any(
            module_prefix_contains(module, group_prefix)
            for group in self.groups
            for group_prefix in group.prefixes
        )

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


def _first_shadowed_prefix(
    group: ModuleGroup,
    prefix: str,
    earlier_groups: tuple[ModuleGroup, ...],
) -> ShadowedPrefix | None:
    """Return the earliest earlier-group prefix that contains ``prefix``."""
    for earlier_group in earlier_groups:
        for earlier_prefix in earlier_group.prefixes:
            if module_prefix_contains(earlier_prefix, prefix):
                return ShadowedPrefix(
                    shadowed_group=group.name,
                    shadowed_prefix=prefix,
                    winning_group=earlier_group.name,
                    winning_prefix=earlier_prefix,
                )
    return None


def find_shadowed_prefixes(
    groups: tuple[ModuleGroup, ...],
) -> tuple[ShadowedPrefix, ...]:
    """Find later-group prefixes already covered by an earlier group.

    For each prefix in each later group, return the first containing prefix in
    the earliest earlier group. Prefixes within one group are intentionally not
    compared, since they cannot change which group first-match classification
    selects.
    """
    shadowed: list[ShadowedPrefix] = []
    for group_index, group in enumerate(groups):
        for prefix in group.prefixes:
            match = _first_shadowed_prefix(group, prefix, groups[:group_index])
            if match is not None:
                shadowed.append(match)
    return tuple(shadowed)


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
