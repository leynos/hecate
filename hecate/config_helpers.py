"""Internal configuration parsing helpers."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from .diagnostics import UNCLASSIFIED_MODULE_RULE_ID
from .policy import UNCLASSIFIED_MODULE_MODES, Severity

if typ.TYPE_CHECKING:
    from pathlib import Path


class ConfigError(ValueError):
    """Raised when a TOML configuration cannot be loaded or validated."""


@dc.dataclass(frozen=True, slots=True)
class _Loc:
    """Error-reporting location for a configuration read operation."""

    path: Path
    context: str = "tool.hecate"


def _validate_dotted_strings(values: tuple[str, ...], loc: _Loc) -> None:
    for value in values:
        if _is_invalid_dotted_string(value):
            msg = f"{loc.path}: {loc.context} contains invalid dotted string {value!r}"
            raise ConfigError(msg)


def _validate_rule_id(rule_id: str, path: Path) -> None:
    """Reject the fixed identifier used by unclassified-module diagnostics.

    Edge diagnostics carry the configured identifier, so reusing the module
    diagnostic's identifier would make the two rules indistinguishable.
    """
    if rule_id != UNCLASSIFIED_MODULE_RULE_ID:
        return
    msg = (
        f"{path}: default_rule_id {UNCLASSIFIED_MODULE_RULE_ID!r} is reserved "
        "for unclassified-module diagnostics; choose another rule identifier"
    )
    raise ConfigError(msg)


def _validate_package_roots(package_roots: tuple[Path, ...], path: Path) -> None:
    if not package_roots:
        msg = f"{path}: at least one package root is required"
        raise ConfigError(msg)
    for package_root in package_roots:
        if not package_root.is_dir():
            msg = f"{path}: package root {package_root} is not a directory"
            raise ConfigError(msg)


def _is_invalid_dotted_string(value: str) -> bool:
    if _has_invalid_dot_placement(value):
        return True
    return any(not segment.isidentifier() for segment in value.split("."))


def _has_invalid_dot_placement(value: str) -> bool:
    return not value or value.startswith((".",)) or value.endswith(".") or ".." in value


def _read_mapping(
    data: dict[str, object], key: str, *, path: Path
) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        msg = f"{path}: missing table {key}"
        raise ConfigError(msg)
    return typ.cast("dict[str, object]", value)


def _read_string(
    data: dict[str, object],
    key: str,
    loc: _Loc,
    *,
    default: str | None = None,
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        msg = f"{loc.path}: {loc.context}.{key} must be a non-empty string"
        raise ConfigError(msg)
    return value


def _read_string_tuple(
    data: dict[str, object],
    key: str,
    loc: _Loc,
) -> tuple[str, ...]:
    value = data.get(key)
    if not _is_non_empty_string_list(value):
        msg = f"{loc.path}: {loc.context}.{key} must be a non-empty string list"
        raise ConfigError(msg)
    return tuple(typ.cast("list[str]", value))


def _is_non_empty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _read_bool(data: dict[str, object], key: str, *, default: bool, path: Path) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        msg = f"{path}: tool.hecate.{key} must be a boolean"
        raise ConfigError(msg)
    return value


@dc.dataclass(frozen=True, slots=True)
class _Choice:
    """One configuration key restricted to a documented set of values."""

    key: str
    values: tuple[str, ...]
    default: str


_UNCLASSIFIED_MODULES_CHOICE = _Choice(
    key="unclassified_modules",
    values=UNCLASSIFIED_MODULE_MODES,
    default="ignore",
)


def _read_choice(data: dict[str, object], choice: _Choice, loc: _Loc) -> str:
    """Read a key restricted to a documented set of string values.

    The permitted values are listed in the error message, so an unsupported
    value names the alternatives instead of merely reporting a type mismatch.
    """
    value = data.get(choice.key, choice.default)
    if not isinstance(value, str) or value not in choice.values:
        permitted = ", ".join(f'"{allowed}"' for allowed in choice.values)
        msg = f"{loc.path}: {loc.context}.{choice.key} must be one of {permitted}"
        raise ConfigError(msg)
    return value


def _read_severity(
    data: dict[str, object],
    key: str,
    *,
    default: Severity,
    path: Path,
) -> Severity:
    """Read a severity value, rejecting unknown names with a clear error."""
    value = data.get(key, default.value)
    if not isinstance(value, str):
        msg = f"{path}: tool.hecate.{key} must be a string"
        raise ConfigError(msg)
    try:
        return Severity(value)
    except ValueError as error:
        allowed = ", ".join(severity.value for severity in Severity)
        msg = f"{path}: tool.hecate.{key} must be one of: {allowed}"
        raise ConfigError(msg) from error
