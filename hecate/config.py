"""TOML configuration loading and validation."""
# pylint: disable=too-many-arguments

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


def load_policy(path: Path | None = None) -> ArchitecturePolicy:
    """Load only the architecture policy from TOML configuration."""
    return load_config(path).policy


def load_config(
    path: Path | None = None,
    *,
    package: str | None = None,
    root: Path | None = None,
    include_external_packages: bool | None = None,
    show_ignored: bool = False,
    fail_on_unmatched_ignore: bool = False,
) -> HecateConfig:
    """Load, validate, and apply CLI overrides to Hecate configuration."""
    config_path = discover_config(path)
    data = _read_tool_config(config_path)
    packages = _parse_packages(data, config_path, package=package, root=root)
    groups = _parse_groups(data, config_path)
    ignores = _parse_ignores(data, config_path)
    configured_include_external = _read_bool(
        data, "include_external_packages", default=False, path=config_path
    )
    policy = ArchitecturePolicy(
        groups=groups,
        ignores=ignores,
        default_rule_id=_read_string(
            data, "default_rule_id", default="HEC001", path=config_path
        ),
        include_external_packages=(
            configured_include_external
            if include_external_packages is None
            else include_external_packages
        ),
    )
    _validate_policy(policy, config_path)
    _validate_package_roots(packages, config_path)
    return HecateConfig(
        packages=packages,
        policy=policy,
        source_path=config_path,
        show_ignored=show_ignored,
        fail_on_unmatched_ignore=fail_on_unmatched_ignore,
    )


def discover_config(path: Path | None = None) -> Path:
    """Find the explicit config path or the nearest ``pyproject.toml``."""
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


def _parse_packages(
    data: dict[str, object],
    path: Path,
    *,
    package: str | None,
    root: Path | None,
) -> tuple[PackageRoot, ...]:
    if package is not None or root is not None:
        if package is None or root is None:
            msg = f"{path}: --package and --root must be provided together"
            raise ConfigError(msg)
        return (PackageRoot(name=package, root=root),)
    configured = data.get("package")
    if configured is None:
        package_names = _read_string_tuple(data, "root_packages", path=path)
        return tuple(
            PackageRoot(name=name, root=_resolve_config_path(path, Path(name)))
            for name in package_names
        )
    if not isinstance(configured, list):
        msg = f"{path}: tool.hecate.package must be a list of tables"
        raise ConfigError(msg)
    packages: list[PackageRoot] = []
    for index, item in enumerate(configured):
        if not isinstance(item, dict):
            msg = f"{path}: tool.hecate.package[{index}] must be a table"
            raise ConfigError(msg)
        package_item = typ.cast("dict[str, object]", item)
        name = _read_string(
            package_item, "name", path=path, context=f"package[{index}]"
        )
        package_root = _read_string(
            package_item, "root", path=path, context=f"package[{index}]"
        )
        packages.append(
            PackageRoot(
                name=name,
                root=_resolve_config_path(path, Path(package_root)),
            )
        )
    return tuple(packages)


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
        parsed.append(
            ModuleGroup(
                name=_read_string(group_item, "name", path=path, context=context),
                prefixes=_read_string_tuple(
                    group_item, "prefixes", path=path, context=context
                ),
                allowed=_read_string_tuple(
                    group_item, "allowed", path=path, context=context
                ),
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
        parsed.append(
            IgnoredImport(
                importer=_read_string(
                    ignore_item, "importer", path=path, context=context
                ),
                imported=_read_string(
                    ignore_item, "imported", path=path, context=context
                ),
                reason=_read_string(ignore_item, "reason", path=path, context=context),
            )
        )
    return tuple(parsed)


def _validate_policy(policy: ArchitecturePolicy, path: Path) -> None:
    group_names = [group.name for group in policy.groups]
    duplicate_names = sorted({
        name for name in group_names if group_names.count(name) > 1
    })
    if duplicate_names:
        msg = f"{path}: duplicate group names: {', '.join(duplicate_names)}"
        raise ConfigError(msg)
    declared_names = set(group_names)
    for group in policy.groups:
        _validate_dotted_strings(group.prefixes, path, context=f"group {group.name}")
        unknown_allowed = sorted(set(group.allowed) - declared_names)
        if unknown_allowed:
            msg = (
                f"{path}: group {group.name} allows undeclared groups: "
                f"{', '.join(unknown_allowed)}"
            )
            raise ConfigError(msg)
    for ignored_import in policy.ignores:
        if not ignored_import.reason.strip():
            msg = (
                f"{path}: ignore {ignored_import.importer} -> "
                f"{ignored_import.imported} needs a reason"
            )
            raise ConfigError(msg)


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


def _validate_dotted_strings(
    values: tuple[str, ...], path: Path, *, context: str
) -> None:
    for value in values:
        if _is_invalid_dotted_string(value):
            msg = f"{path}: {context} contains invalid dotted string {value!r}"
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


def _read_string(
    data: dict[str, object],
    key: str,
    *,
    path: Path,
    context: str = "tool.hecate",
    default: str | None = None,
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        msg = f"{path}: {context}.{key} must be a non-empty string"
        raise ConfigError(msg)
    return value


def _read_string_tuple(
    data: dict[str, object],
    key: str,
    *,
    path: Path,
    context: str = "tool.hecate",
) -> tuple[str, ...]:
    value = data.get(key)
    if not _is_non_empty_string_list(value):
        msg = f"{path}: {context}.{key} must be a non-empty string list"
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
