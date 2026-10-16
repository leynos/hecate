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


def _require[T](value: object, kind: type[T], message: str) -> T:
    """Return ``value`` once it is a ``kind``, or fail with ``message``.

    The readers below share one shape -- fetch a configured entry, reject it
    when it is not the expected type, keep it otherwise -- and each supplies
    its own diagnostic. Keeping the type test here leaves the wording with the
    key that knows it, rather than restating the same test per reader.

    Parameters
    ----------
    value : object
        The configured value being read.
    kind : type[T]
        The type the value must have.
    message : str
        Diagnostic naming the offending key and the type it must hold.

    Returns
    -------
    T
        ``value``, narrowed to ``kind``.

    Raises
    ------
    ConfigError
        If ``value`` is not an instance of ``kind``.
    """
    if not isinstance(value, kind):
        raise ConfigError(message)
    return value


def _validate_dotted_strings(values: tuple[str, ...], loc: _Loc) -> None:
    for value in values:
        if _is_invalid_dotted_string(value):
            msg = f"{loc.path}: {loc.context} contains invalid dotted string {value!r}"
            raise ConfigError(msg)


def _is_invalid_dotted_string(value: str) -> bool:
    """Return whether ``value`` is not a dot-separated run of identifiers.

    Splitting on every dot subsumes the placement cases: an empty string, a
    leading or trailing dot, and an interior ``""`` each yield a segment that
    is not an identifier, so none of them needs a separate check.
    """
    return any(not segment.isidentifier() for segment in value.split("."))


def _read_mapping(
    data: dict[str, object], key: str, *, path: Path
) -> dict[str, object]:
    msg = f"{path}: missing table {key}"
    return _require(data.get(key), dict, msg)


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
    tables = _require(value, list, f"{path}: {key} must be a list of tables")
    return [
        _require(item, dict, f"{path}: {key}[{index}] must be a table")
        for index, item in enumerate(tables)
    ]


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
    msg = f"{path}: tool.hecate.{key} must be a boolean"
    return _require(data.get(key, default), bool, msg)


def _read_severity(
    data: dict[str, object],
    key: str,
    *,
    default: Severity,
    path: Path,
) -> Severity:
    """Read a severity value, rejecting unknown names with a clear error."""
    msg = f"{path}: tool.hecate.{key} must be a string"
    value = _require(data.get(key, default.value), str, msg)
    try:
        return Severity(value)
    except ValueError as error:
        allowed = ", ".join(severity.value for severity in Severity)
        unknown = f"{path}: tool.hecate.{key} must be one of: {allowed}"
        raise ConfigError(unknown) from error
