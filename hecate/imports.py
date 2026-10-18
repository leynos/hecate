"""Static import collection based on the Python standard library AST."""

from __future__ import annotations

import ast
import dataclasses as dc
import typing as typ
from pathlib import Path

from .source import parse_source

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class DiscoveryError(ValueError):
    """Raised when a package root cannot be walked completely."""


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


@dc.dataclass(frozen=True, slots=True)
class DiscoveredModule:
    """One ``*.py`` file beneath a package root, paired with its dotted name."""

    module: str
    source_path: Path
    is_package_init: bool = False
    """Whether this record is a package ``__init__.py``.

    Python resolves a name to the package's initializer in preference to a
    sibling module spelled the same way, so a caller deciding which record owns
    a dotted name needs this rather than the path alone.
    """


@dc.dataclass(frozen=True, slots=True)
class Discovery:
    """One package root's modules, walked once and shared by every pass.

    Carrying the root's identity alongside its files keeps this record free of
    any dependency on the configuration model, so discovery stays a property of
    the tree rather than of how a caller happened to declare it.
    """

    package: str
    root: Path
    modules: tuple[DiscoveredModule, ...]


def discover_modules(root: Path, package: str) -> Discovery:
    """Return every module beneath ``root``, ordered by source path.

    One walk serves every pass that needs to know which files a root holds, so
    the passes cannot disagree about what exists. Sorting here rather than in
    each caller makes traversal order a property of the tree instead of the
    filesystem, and gives a caller that keys a mapping by module name
    first-record semantics from this order alone.

    Every record carries ``is_package_init`` so a caller can tell the module a
    package resolves to from a plain module with the same dotted name, without
    re-deriving it from the path.

    Raises
    ------
    DiscoveryError
        A directory beneath ``root`` could not be listed. Discovery never
        silently returns a partial tree: a missing subtree would read as clean
        coverage of files the walk never saw.
    """
    source_paths = sorted(_walk_source_paths(root))
    return Discovery(
        package=package,
        root=root,
        modules=tuple(
            DiscoveredModule(
                module=compute_module_name(root, package, source_path),
                source_path=source_path,
                is_package_init=source_path.name == "__init__.py",
            )
            for source_path in source_paths
        ),
    )


def _walk_source_paths(root: Path) -> cabc.Iterator[Path]:
    """Yield every ``*.py`` file beneath ``root``, surfacing traversal errors.

    ``Path.rglob`` and ``Path.glob`` swallow ``OSError`` and return whatever
    they managed to list, so an unreadable subtree would look like an empty
    one. ``Path.walk`` reports the failure to ``on_error`` instead, which this
    walk turns into :class:`DiscoveryError` naming the directory to fix.
    """

    def fail_with_context(error: OSError) -> typ.NoReturn:
        msg = f"{error.filename}: cannot list directory: {error.strerror}"
        raise DiscoveryError(msg) from error

    for directory, _, filenames in root.walk(on_error=fail_with_context):
        for filename in filenames:
            if filename.endswith(".py"):
                yield directory / filename


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
    module: str,
) -> tuple[ImportStatement, ...]:
    """Collect import statements from a Python source file.

    ``module`` is the dotted name for ``source_path``, as supplied by
    :func:`discover_modules`. Taking it rather than deriving it here keeps one
    mapping from path to name, so the importer recorded on each statement is the
    same name the rest of the run knows the file by.

    Statements are returned in source order so that later analysis can apply
    Python's last-binding-wins rules when several statements bind one name.
    ``ast.walk`` yields breadth-first, which is not source order once an import
    is nested in a block, so the collected nodes are sorted before conversion.
    """
    module_name = module
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
