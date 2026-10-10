"""Static import collection based on the Python standard library AST."""

from __future__ import annotations

import ast
import dataclasses as dc
from pathlib import Path

from .source import parse_source


@dc.dataclass(frozen=True, slots=True)
class DirectImport:
    """An ``import a.b`` statement binding ``a`` in the importing module."""

    importer: str
    module: str
    line: int
    source_path: Path


@dc.dataclass(frozen=True, slots=True)
class FromImport:
    """A ``from target import names`` statement.

    ``names`` preserves source order and includes ``"*"`` entries verbatim, so
    that later analysis can apply Python's wildcard rules rather than assuming
    every listed name denotes a symbol.
    """

    importer: str
    target: str
    names: tuple[str, ...]
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


ImportStatement = DirectImport | FromImport


def collect_import_statements(
    source_path: Path,
    *,
    root: Path,
    package: str,
) -> tuple[ImportStatement, ...]:
    """Collect import statements from a Python source file.

    Statements are returned in source order so that later analysis can apply
    Python's last-binding-wins rules when several statements bind one name.
    ``ast.walk`` yields breadth-first, which is not source order once an import
    is nested in a block, so the collected nodes are sorted before conversion.
    """
    module_name = compute_module_name(root, package, source_path)
    tree = parse_source(source_path)
    is_package_init = source_path.name == "__init__.py"
    statements: list[ImportStatement] = []
    for node in sorted(_import_nodes(tree), key=_source_position):
        if isinstance(node, ast.Import):
            statements.extend(_collect_direct_imports(node, module_name, source_path))
        elif isinstance(node, ast.ImportFrom):
            statements.extend(
                _collect_from_imports(
                    node,
                    module_name=module_name,
                    is_package_init=is_package_init,
                    source_path=source_path,
                )
            )
    return tuple(statements)


def _import_nodes(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Return every import node in ``tree``, in arbitrary order."""
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)
    ]


def _source_position(node: ast.Import | ast.ImportFrom) -> tuple[int, int]:
    """Return an import node's position, so collected statements sort sanely."""
    return (node.lineno, node.col_offset)


def _collect_direct_imports(
    node: ast.Import, importer: str, source_path: Path
) -> tuple[DirectImport, ...]:
    return tuple(
        DirectImport(
            importer=importer,
            module=alias.name,
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
) -> tuple[FromImport, ...]:
    imported_module = resolve_import_from(
        module_name,
        is_package_init=is_package_init,
        level=node.level,
        imported_module=node.module,
    )
    if imported_module is None:
        return ()
    return (
        FromImport(
            importer=module_name,
            target=imported_module,
            names=tuple(alias.name for alias in node.names),
            line=node.lineno,
            source_path=source_path,
        ),
    )


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
