"""TOML configuration loading and validation."""
# pylint: disable=too-many-lines

from __future__ import annotations

import dataclasses as dc
import tomllib
import typing as typ
from pathlib import Path

from .policy import ArchitecturePolicy, IgnoredImport, ModuleGroup


@dc.dataclass(frozen=True, slots=True)
class PackageRoot:
    """One Python package root scanned by Hecate."""

    name: str
    root: Path


@dc.dataclass(frozen=True, slots=True)
class HecateConfig:
    """Complete checker configuration."""

    packages: tuple[PackageRoot, ...]
    policy: ArchitecturePolicy
    source_path: Path | None = None
    show_ignored: bool = False
    fail_on_unmatched_ignore: bool = False


class ConfigError(ValueError):
    """Raised when a TOML configuration cannot be loaded or validated."""


@dc.dataclass(frozen=True)
class ConfigOverrides:
    """CLI-level overrides applied on top of the TOML configuration."""

    package: str | None = None
    root: Path | None = None
    include_external_packages: bool | None = None
    show_ignored: bool = False
    fail_on_unmatched_ignore: bool = False


def load_policy(path: Path | None = None) -> ArchitecturePolicy:
    """Load the architecture policy from TOML configuration.

    This is a convenience wrapper around ``load_config`` for callers that only
    need the validated policy object.

    Parameters
    ----------
    path : Path | None
        Explicit TOML configuration file. When omitted, Hecate discovers the
        nearest ``pyproject.toml``.

    Returns
    -------
    ArchitecturePolicy
        Validated architecture policy from the configuration.

    Raises
    ------
    ConfigError
        The configuration file is missing, malformed, or invalid.
    tomllib.TOMLDecodeError
        Wrapped in ``ConfigError`` when TOML decoding fails.
    """
    return load_config(path).policy


def load_config(
    path: Path | None = None,
    overrides: ConfigOverrides | None = None,
) -> HecateConfig:
    """Load, validate, and apply CLI overrides to Hecate configuration."""
    ov = overrides or ConfigOverrides()
    config_path = discover_config(path)
    data = _read_tool_config(config_path)
    packages = _parse_packages(data, config_path, package=ov.package, root=ov.root)
    groups = _parse_groups(data, config_path)
    ignores = _parse_ignores(data, config_path)
    configured_include_external = _read_bool(
        data, "include_external_packages", default=False, path=config_path
    )
    policy = ArchitecturePolicy(
        groups=groups,
        ignores=ignores,
        default_rule_id=_read_string(
            data, "default_rule_id", _Loc(path=config_path), default="HEC001"
        ),
        include_external_packages=(
            configured_include_external
            if ov.include_external_packages is None
            else ov.include_external_packages
        ),
    )
    _validate_policy(policy, config_path)
    _validate_package_roots(packages, config_path)
    return HecateConfig(
        packages=packages,
        policy=policy,
        source_path=config_path,
        show_ignored=ov.show_ignored,
        fail_on_unmatched_ignore=ov.fail_on_unmatched_ignore,
    )


def discover_config(path: Path | None = None) -> Path:
    """Find the explicit config path or nearest ``pyproject.toml``.

    Parameters
    ----------
    path : Path | None
        Explicit TOML configuration file. When provided, it is returned without
        filesystem discovery.

    Returns
    -------
    Path
        Explicit path or discovered ``pyproject.toml`` path.

    Raises
    ------
    ConfigError
        No ``pyproject.toml`` can be found from the current working directory.
    """
    if path is not None:
        return path
    current = Path.cwd()
    for candidate_root in (current, *current.parents):
        candidate = candidate_root / "pyproject.toml"
        if candidate.is_file():
            return candidate
    msg = "No pyproject.toml found for [tool.hecate] configuration"
    raise ConfigError(msg)


def _read_tool_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        msg = f"{path}: configuration file does not exist"
        raise ConfigError(msg)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"{path}: invalid TOML: {error}"
        raise ConfigError(msg) from error
    tool = _read_mapping(data, "tool", path=path)
    return _read_mapping(tool, "hecate", path=path)


def _parse_package_from_cli_args(
    package: str | None, root: Path | None, path: Path
) -> tuple[PackageRoot, ...] | None:
    """Return a single-item tuple when CLI overrides are supplied, or None."""
    if package is None and root is None:
        return None
    if package is None or root is None:
        msg = f"{path}: --package and --root must be provided together"
        raise ConfigError(msg)
    return (PackageRoot(name=package, root=root),)


def _parse_root_packages(
    data: dict[str, object],
    path: Path,
) -> tuple[PackageRoot, ...]:
    """Build package roots from the ``root_packages`` string list."""
    package_names = _read_string_tuple(data, "root_packages", _Loc(path=path))
    return tuple(
        PackageRoot(name=name, root=_resolve_config_path(path, Path(name)))
        for name in package_names
    )


def _parse_package_table_item(item: object, index: int, path: Path) -> PackageRoot:
    """Parse and validate one entry from the ``package`` table list."""
    if not isinstance(item, dict):
        msg = f"{path}: tool.hecate.package[{index}] must be a table"
        raise ConfigError(msg)
    package_item = typ.cast("dict[str, object]", item)
    loc = _Loc(path=path, context=f"package[{index}]")
    name = _read_string(package_item, "name", loc)
    package_root_str = _read_string(package_item, "root", loc)
    return PackageRoot(
        name=name, root=_resolve_config_path(path, Path(package_root_str))
    )


def _parse_packages(
    data: dict[str, object],
    path: Path,
    *,
    package: str | None,
    root: Path | None,
) -> tuple[PackageRoot, ...]:
    cli_package = _parse_package_from_cli_args(package, root, path)
    if cli_package is not None:
        return cli_package
    configured = data.get("package")
    if configured is None:
        return _parse_root_packages(data, path)
    if not isinstance(configured, list):
        msg = f"{path}: tool.hecate.package must be a list of tables"
        raise ConfigError(msg)
    return tuple(
        _parse_package_table_item(item, index, path)
        for index, item in enumerate(configured)
    )


def _parse_groups(data: dict[str, object], path: Path) -> tuple[ModuleGroup, ...]:
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        msg = f"{path}: tool.hecate.groups must be a non-empty list of tables"
        raise ConfigError(msg)
    parsed: list[ModuleGroup] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            msg = f"{path}: tool.hecate.groups[{index}] must be a table"
            raise ConfigError(msg)
        group_item = typ.cast("dict[str, object]", group)
        context = f"groups[{index}]"
        loc = _Loc(path=path, context=context)
        parsed.append(
            ModuleGroup(
                name=_read_string(group_item, "name", loc),
                prefixes=_read_string_tuple(group_item, "prefixes", loc),
                allowed=_read_string_tuple(group_item, "allowed", loc),
            )
        )
    return tuple(parsed)


def _parse_ignores(data: dict[str, object], path: Path) -> tuple[IgnoredImport, ...]:
    ignores = data.get("ignore_imports", [])
    if not isinstance(ignores, list):
        msg = f"{path}: tool.hecate.ignore_imports must be a list of tables"
        raise ConfigError(msg)
    parsed: list[IgnoredImport] = []
    for index, item in enumerate(ignores):
        if not isinstance(item, dict):
            msg = f"{path}: tool.hecate.ignore_imports[{index}] must be a table"
            raise ConfigError(msg)
        ignore_item = typ.cast("dict[str, object]", item)
        context = f"ignore_imports[{index}]"
        loc = _Loc(path=path, context=context)
        parsed.append(
            IgnoredImport(
                importer=_read_string(ignore_item, "importer", loc),
                imported=_read_string(ignore_item, "imported", loc),
                reason=_read_string(ignore_item, "reason", loc),
            )
        )
    return tuple(parsed)


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
    """Validate prefixes and allowed-group references for one group."""
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


def _validate_policy(policy: ArchitecturePolicy, path: Path) -> None:
    group_names = [group.name for group in policy.groups]
    _check_duplicate_group_names(group_names, path)
    declared_names = set(group_names)
    for group in policy.groups:
        _validate_group_references(group, declared_names, path)
    for ignored_import in policy.ignores:
        _validate_ignore_reason(ignored_import, path)


def _validate_package_roots(packages: tuple[PackageRoot, ...], path: Path) -> None:
    if not packages:
        msg = f"{path}: at least one package root is required"
        raise ConfigError(msg)
    for package_root in packages:
        if not package_root.root.is_dir():
            msg = f"{path}: package root {package_root.root} is not a directory"
            raise ConfigError(msg)


def _resolve_config_path(config_path: Path, configured_path: Path) -> Path:
    if configured_path.is_absolute():
        return configured_path
    return config_path.parent / configured_path


def _validate_dotted_strings(values: tuple[str, ...], loc: _Loc) -> None:
    for value in values:
        if _is_invalid_dotted_string(value):
            msg = f"{loc.path}: {loc.context} contains invalid dotted string {value!r}"
            raise ConfigError(msg)


def _is_invalid_dotted_string(value: str) -> bool:
    return not value or value.startswith((".",)) or value.endswith(".") or ".." in value


def _read_mapping(
    data: dict[str, object], key: str, *, path: Path
) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        msg = f"{path}: missing table {key}"
        raise ConfigError(msg)
    return typ.cast("dict[str, object]", value)


@dc.dataclass(frozen=True, slots=True)
class _Loc:
    """Error-reporting location for a configuration read operation."""

    path: Path
    context: str = "tool.hecate"


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
