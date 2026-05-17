"""Package barrel re-export indexing."""

from __future__ import annotations

import ast
import dataclasses as dc
from pathlib import Path

from .config import PackageRoot
from .imports import compute_module_name, resolve_import_from


@dc.dataclass(frozen=True, slots=True)
class ReexportIndex:
    """Static mapping from exported dotted names to original dotted names."""

    exports: dict[str, tuple[str, ...]]

    def expand_import(self, imported: str) -> tuple[str, ...]:
        """Return the import target plus any statically resolved origins."""
        return tuple(self._expand_import(imported, seen=set()))

    def _expand_import(self, imported: str, *, seen: set[str]) -> tuple[str, ...]:
        """Recursively expand one import target through package barrels."""
        if imported in seen:
            return ()
        seen.add(imported)
        expanded = [imported]
        for origin in self.exports.get(imported, ()):
            expanded.extend(self._expand_import(origin, seen=seen))
        return tuple(dict.fromkeys(expanded))


@dc.dataclass(frozen=True, slots=True)
class _ModuleExports:
    module: str
    exports: dict[str, tuple[str, ...]]


def build_reexport_index(packages: tuple[PackageRoot, ...]) -> ReexportIndex:
    """Build re-export mappings for all scanned package roots."""
    module_exports = _collect_module_exports(packages)
    reexports: dict[str, tuple[str, ...]] = {}
    for package_root in packages:
        for init_path in sorted(package_root.root.rglob("__init__.py")):
            module = compute_module_name(
                package_root.root, package_root.name, init_path
            )
            _add_module_reexports(module, module_exports, reexports)
    return ReexportIndex(exports=reexports)


def _add_module_reexports(
    module: str,
    module_exports: dict[str, _ModuleExports],
    reexports: dict[str, tuple[str, ...]],
) -> None:
    for exported_name, origins in module_exports[module].exports.items():
        if exported_name == "*":
            _add_star_reexports(module, origins, module_exports, reexports)
            continue
        reexports[f"{module}.{exported_name}"] = _expand_origins(
            origins, module_exports
        )


def _add_star_reexports(
    module: str,
    origins: tuple[str, ...],
    module_exports: dict[str, _ModuleExports],
    reexports: dict[str, tuple[str, ...]],
) -> None:
    for origin in origins:
        for star_origin in _expand_origin(origin, module_exports):
            name = star_origin.rsplit(".", maxsplit=1)[-1]
            reexports[f"{module}.{name}"] = (star_origin,)


def _collect_module_exports(
    packages: tuple[PackageRoot, ...],
) -> dict[str, _ModuleExports]:
    exports: dict[str, _ModuleExports] = {}
    for package_root in packages:
        for source_path in sorted(package_root.root.rglob("*.py")):
            module = compute_module_name(
                package_root.root, package_root.name, source_path
            )
            exports[module] = _exports_for_module(source_path, module)
    return exports


def _exports_for_module(source_path: Path, module: str) -> _ModuleExports:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    all_names = _literal_all_names(tree)
    collected = _collect_public_exports(
        tree,
        module=module,
        is_package_init=source_path.name == "__init__.py",
    )
    if all_names is None:
        return _ModuleExports(module=module, exports=collected)
    return _ModuleExports(
        module=module,
        exports={
            name: collected.get(name, (f"{module}.{name}",))
            for name in all_names
            if not name.startswith("_")
        },
    )


def _literal_all_names(tree: ast.Module) -> tuple[str, ...] | None:
    last_assignment: tuple[str, ...] | None = None
    for node in tree.body:
        value = _all_assignment_value(node)
        if value is not None:
            last_assignment = _literal_string_sequence(value)
    return last_assignment


def _all_assignment_value(node: ast.stmt) -> ast.expr | None:
    if isinstance(node, ast.Assign) and _assigns_all(node.targets):
        return node.value
    if isinstance(node, ast.AnnAssign) and _target_is_all(node.target):
        return node.value
    return None


def _assigns_all(targets: list[ast.expr]) -> bool:
    return any(_target_is_all(target) for target in targets)


def _target_is_all(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == "__all__"


def _literal_string_sequence(value: ast.expr) -> tuple[str, ...] | None:
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    names: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.append(element.value)
    return tuple(names)


def _collect_public_exports(
    tree: ast.Module, *, module: str, is_package_init: bool
) -> dict[str, tuple[str, ...]]:
    exports: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                exports[node.name] = (f"{module}.{node.name}",)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    exports[target.id] = (f"{module}.{target.id}",)
        elif isinstance(node, ast.ImportFrom):
            _merge_exports(
                exports,
                _collect_imported_exports(
                    node, module=module, is_package_init=is_package_init
                ),
            )
    return exports


def _merge_exports(
    exports: dict[str, tuple[str, ...]], additions: dict[str, tuple[str, ...]]
) -> None:
    for exported_name, origins in additions.items():
        exports[exported_name] = (*exports.get(exported_name, ()), *origins)


def _collect_imported_exports(
    node: ast.ImportFrom, *, module: str, is_package_init: bool
) -> dict[str, tuple[str, ...]]:
    imported_module = resolve_import_from(
        module,
        is_package_init=is_package_init,
        level=node.level,
        imported_module=node.module,
    )
    if imported_module is None:
        return {}
    exports: dict[str, tuple[str, ...]] = {}
    for alias in node.names:
        if alias.name == "*":
            exports["*"] = (*exports.get("*", ()), f"{imported_module}.*")
            continue
        exported_name = alias.asname or alias.name
        if not exported_name.startswith("_"):
            exports[exported_name] = (f"{imported_module}.{alias.name}",)
    return exports


def _expand_origins(
    origins: tuple[str, ...], module_exports: dict[str, _ModuleExports]
) -> tuple[str, ...]:
    expanded: list[str] = []
    for origin in origins:
        expanded.extend(_expand_origin(origin, module_exports))
    return tuple(dict.fromkeys(expanded))


def _expand_origin(
    origin: str, module_exports: dict[str, _ModuleExports]
) -> tuple[str, ...]:
    if not origin.endswith(".*"):
        return (origin,)
    module = origin.removesuffix(".*")
    if module not in module_exports:
        return (origin,)
    expanded: list[str] = []
    for origins in module_exports[module].exports.values():
        expanded.extend(_expand_origins(origins, module_exports))
    return tuple(sorted(dict.fromkeys(expanded)))
