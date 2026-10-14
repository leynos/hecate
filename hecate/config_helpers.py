"""Internal configuration parsing helpers."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from .policy import Severity

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


def _read_table_list(
    value: object,
    *,
    key: str,
    path: Path,
) -> list[dict[str, object]]:
    """Validate a configured list-of-tables and return its tables.

    This checks shape only. An empty array is a well-formed table list, so a
    key that must hold at least one table states that requirement at its own
    call site rather than through a mode argument here; that keeps this helper
    answering one question instead of switching between two.

    Parameters
    ----------
    value : object
        The configured array being read.
    key : str
        Dotted configuration key naming the array, such as
        ``tool.hecate.groups``, used in every diagnostic.
    path : Path
        Configuration file the value came from, used in every diagnostic.

    Returns
    -------
    list[dict[str, object]]
        The validated tables, in configured order, possibly empty.

    Raises
    ------
    ConfigError
        If the value is not an array of tables.
    """
    if not isinstance(value, list):
        msg = f"{path}: {key} must be a list of tables"
        raise ConfigError(msg)
    parsed: list[dict[str, object]] = []
    for index, item in enumerate(typ.cast("list[object]", value)):
        if not isinstance(item, dict):
            msg = f"{path}: {key}[{index}] must be a table"
            raise ConfigError(msg)
        parsed.append(typ.cast("dict[str, object]", item))
    return parsed


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
