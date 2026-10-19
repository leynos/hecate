"""Configuration validation rules and their diagnostics.

The loader reads and parses TOML; this module turns the resulting model into
the path-qualified messages a user sees when a policy is malformed. Keeping
the rules here lets ``config.py`` stay a reader, and gives each message one
place to live.
"""

from __future__ import annotations

import typing as typ

from .config_helpers import ConfigError, _Loc, _validate_dotted_strings
from .policy import ShadowedPrefix, find_shadowed_prefixes

if typ.TYPE_CHECKING:
    from pathlib import Path

    from .policy import ArchitecturePolicy, IgnoredImport, ModuleGroup


def _shadowed_prefix_diagnostics(
    shadows: tuple[ShadowedPrefix, ...], path: Path
) -> tuple[str, ...]:
    """Return one ordered, path-qualified diagnostic for each shadow."""
    return tuple(
        f"{path}: tool.hecate.groups: prefix {shadow.shadowed_prefix!r} in "
        f"group {shadow.shadowed_group!r} is shadowed by earlier prefix "
        f"{shadow.winning_prefix!r} in group {shadow.winning_group!r}; "
        f"{_shadowed_prefix_remedy(shadow)}"
        for shadow in shadows
    )


def _shadowed_prefix_remedy(shadow: ShadowedPrefix) -> str:
    """Describe how to repair one shadowed prefix diagnostic."""
    if shadow.shadowed_prefix == shadow.winning_prefix:
        return (
            f"remove the duplicate prefix {shadow.shadowed_prefix!r} from "
            f"later group {shadow.shadowed_group!r}, or remove every earlier "
            f"prefix that contains {shadow.shadowed_prefix!r}"
        )
    return (
        f"place group {shadow.shadowed_group!r} before group "
        f"{shadow.winning_group!r} and every other earlier group with a "
        f"prefix that contains {shadow.shadowed_prefix!r} to make the narrower "
        f"classification effective, remove the unreachable prefix "
        f"{shadow.shadowed_prefix!r} from group {shadow.shadowed_group!r}, "
        f"remove every earlier prefix that contains "
        f"{shadow.shadowed_prefix!r}, or move it to the group that should own it"
    )


def _check_duplicate_group_names(group_names: list[str], path: Path) -> None:
    """Raise ConfigError if any group name appears more than once."""
    duplicate_names = sorted({
        name for name in group_names if group_names.count(name) > 1
    })
    if duplicate_names:
        msg = f"{path}: duplicate group names: {', '.join(duplicate_names)}"
        raise ConfigError(msg)


def _validate_group_references(
    group: ModuleGroup, declared_names: set[str], path: Path
) -> None:
    """Validate prefixes and allowed/warn group references for one group."""
    _validate_dotted_strings(
        group.prefixes, _Loc(path=path, context=f"group {group.name}")
    )
    unknown_allowed = sorted(set(group.allowed) - declared_names)
    if unknown_allowed:
        msg = (
            f"{path}: group {group.name} allows undeclared groups: "
            f"{', '.join(unknown_allowed)}"
        )
        raise ConfigError(msg)
    unknown_warned = sorted(set(group.warn) - declared_names)
    if unknown_warned:
        msg = (
            f"{path}: group {group.name} warns undeclared groups: "
            f"{', '.join(unknown_warned)}"
        )
        raise ConfigError(msg)


def _validate_target_overlap(group: ModuleGroup, path: Path) -> None:
    """Reject a target listed as both allowed and warning-level.

    The two outcomes contradict: an allowed target is silent and a warning
    target stays visible. Rejecting the overlap keeps each edge's outcome a
    single decidable thing rather than one that depends on evaluation order.
    """
    conflicting = sorted(set(group.allowed) & set(group.warn))
    if conflicting:
        msg = (
            f"{path}: group {group.name} lists targets as both allowed and "
            f"warn: {', '.join(conflicting)}"
        )
        raise ConfigError(msg)


def _validate_ignore_reason(ignored_import: IgnoredImport, path: Path) -> None:
    """Raise ConfigError when an ignore entry carries no reason."""
    _validate_dotted_strings(
        (ignored_import.importer, ignored_import.imported),
        _Loc(path=path, context="ignore_imports entry"),
    )
    if not ignored_import.reason.strip():
        msg = (
            f"{path}: ignore {ignored_import.importer} -> "
            f"{ignored_import.imported} needs a reason"
        )
        raise ConfigError(msg)


def _validate_group_prefix_order(policy: ArchitecturePolicy, path: Path) -> None:
    """Reject prefixes made unreachable by earlier groups."""
    diagnostics = _shadowed_prefix_diagnostics(
        find_shadowed_prefixes(policy.groups), path
    )
    if diagnostics:
        raise ConfigError("\n".join(diagnostics))
