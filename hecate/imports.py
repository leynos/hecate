"""Static import collection based on the Python standard library AST."""

from __future__ import annotations

import ast
import dataclasses as dc
from pathlib import Path


@dc.dataclass(frozen=True, slots=True)
class ImportReference:
    """One import edge found in a Python module."""

    importer: str
    imported: str
    line: int
    source_path: Path


def is_module_prefix(prefix: str, module: str) -> bool:
    """Return whether ``prefix`` contains ``module`` at a dotted boundary."""
    assert prefix
    assert module
    return module == prefix or module.startswith(f"{prefix}.")


def compute_module_name(root: Path, package: str, source_path: Path) -> str:
    """Derive the dotted module name for ``source_path`` under ``root``."""
    relative = source_path.relative_to(root).with_suffix("")
    parts = tuple(part for part in relative.parts if part != "__init__")
    if not parts:
        return package
    return ".".join((package, *parts))


def relative_import_base(module_name: str, *, is_package_init: bool, level: int) -> str:
    """Return the absolute base module for a relative import level."""
    assert module_name
    assert level >= 1
    module_parts = module_name.split(".")
    if not is_package_init:
        module_parts = module_parts[:-1]
    drop_count = level - 1
    if drop_count:
        module_parts = module_parts[:-drop_count]
    return ".".join(module_parts)


def collect_imports(
    source_path: Path,
    *,
    root: Path,
    package: str,
) -> tuple[ImportReference, ...]:
    """Collect direct imports from a Python source file."""
    module_name = compute_module_name(root, package, source_path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imports: list[ImportReference] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(_collect_direct_imports(node, module_name, source_path))
        elif isinstance(node, ast.ImportFrom):
            imports.extend(
                _collect_from_imports(
                    node,
                    module_name=module_name,
                    is_package_init=source_path.name == "__init__.py",
                    source_path=source_path,
                )
            )
    return tuple(imports)


def _collect_direct_imports(
    node: ast.Import, importer: str, source_path: Path
) -> tuple[ImportReference, ...]:
    return tuple(
        ImportReference(
            importer=importer,
            imported=alias.name,
            line=node.lineno,
            source_path=source_path,
        )
        for alias in node.names
    )


def _collect_from_imports(
    node: ast.ImportFrom,
    *,
    module_name: str,
    is_package_init: bool,
    source_path: Path,
) -> tuple[ImportReference, ...]:
    imported_module = resolve_import_from(
        module_name,
        is_package_init=is_package_init,
        level=node.level,
        imported_module=node.module,
    )
    if imported_module is None:
        return ()
    imports = [
        ImportReference(
            importer=module_name,
            imported=imported_module,
            line=node.lineno,
            source_path=source_path,
        )
    ]
    imports.extend(
        ImportReference(
            importer=module_name,
            imported=f"{imported_module}.{alias.name}",
            line=node.lineno,
            source_path=source_path,
        )
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(imports)


def resolve_import_from(
    module_name: str,
    *,
    is_package_init: bool,
    level: int,
    imported_module: str | None,
) -> str | None:
    """Resolve an ``ImportFrom`` node to its absolute module target."""
    if level:
        base = relative_import_base(
            module_name, is_package_init=is_package_init, level=level
        )
        if imported_module:
            return f"{base}.{imported_module}" if base else imported_module
        return base
    return imported_module
