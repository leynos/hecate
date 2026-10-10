"""Module namespace and wildcard-export modelling.

Python's ``__all__`` selects which names a wildcard import picks up. It does
*not* hide module attributes: ``from module import name`` still resolves for any
name bound on the module, whether or not ``__all__`` lists it. Hecate therefore
models two distinct views of each module:

``bindings``
    Names bound on the module, in source order. These are what explicit
    ``from module import name`` statements can reach.

``wildcard exports``
    Names selected by ``from module import *``. When a literal ``__all__``
    assignment provides the selection, those names win verbatim, including
    underscore-prefixed entries. Otherwise the default public-name rule applies
    to the module's own bindings, unioned with the wildcard export sets of every
    module pulled in by ``from origin import *``.

Symbol-origin provenance and policy classification are layered on top of this
model by :mod:`hecate.origins` and :mod:`hecate.policy` respectively.
"""

from __future__ import annotations

import ast
import dataclasses as dc
import typing as typ

from .imports import compute_module_name, resolve_import_from
from .module_scope import module_level_statements

if typ.TYPE_CHECKING:
    from pathlib import Path

    from .config import PackageRoot


@dc.dataclass(frozen=True, slots=True)
class Definition:
    """A name defined directly by the module under analysis."""


@dc.dataclass(frozen=True, slots=True)
class Imported:
    """A name bound on the module by an import statement.

    ``origin`` is the dotted module the name came from and ``symbol`` is the
    attribute to look up there. ``symbol`` is ``None`` for ``import a.b``, where
    the bound name *is* the ``a.b`` module rather than one of its attributes.
    """

    origin: str
    symbol: str | None


Binding = Definition | Imported


@dc.dataclass(frozen=True, slots=True)
class ModuleNamespace:
    """The analysed namespace of one module or package ``__init__``."""

    module: str
    bindings: tuple[tuple[str, Binding], ...]
    """Module-level bindings in source order, so later bindings win."""

    all_names: tuple[str, ...] | None = None
    """Names from the last literal ``__all__`` assignment, or ``None``."""

    wildcard_origins: tuple[str, ...] = ()
    """Modules this one pulls in with ``from origin import *``."""

    @property
    def has_explicit_all(self) -> bool:
        """Return whether a literal ``__all__`` assignment was found."""
        return self.all_names is not None

    @property
    def binding_map(self) -> dict[str, Binding]:
        """Return bound names keyed by name, honouring last-binding-wins."""
        return dict(self.bindings)


def analyse_namespaces(
    packages: tuple[PackageRoot, ...],
) -> dict[str, ModuleNamespace]:
    """Analyse every module under ``packages`` into a namespace model.

    Parameters
    ----------
    packages : tuple of PackageRoot
        Package roots to scan.

    Returns
    -------
    dict of str to ModuleNamespace
        Analysed namespaces keyed by dotted module name.
    """
    namespaces: dict[str, ModuleNamespace] = {}
    for package_root in packages:
        for source_path in sorted(package_root.root.rglob("*.py")):
            module = compute_module_name(
                package_root.root, package_root.name, source_path
            )
            namespaces[module] = analyse_module(source_path, module=module)
    return namespaces


def analyse_module(source_path: Path, *, module: str) -> ModuleNamespace:
    """Analyse one source file into its :class:`ModuleNamespace`."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    return analyse_namespace(
        tree, module=module, is_package_init=source_path.name == "__init__.py"
    )


def analyse_namespace(
    tree: ast.Module, *, module: str, is_package_init: bool
) -> ModuleNamespace:
    """Analyse a parsed module into its :class:`ModuleNamespace`.

    Parameters
    ----------
    tree : ast.Module
        Parsed module to analyse.
    module : str
        Dotted name of the module being analysed.
    is_package_init : bool
        Whether the module is a package ``__init__``, which changes how
        relative imports resolve.

    Returns
    -------
    ModuleNamespace
        Bindings in source order plus the raw wildcard export selection.
    """
    bindings: dict[str, Binding] = {}
    wildcard_origins: list[str] = []
    for node, _ in module_level_statements(tree.body):
        bindings.update(
            _bindings_from_statement(
                node, module=module, is_package_init=is_package_init
            )
        )
        wildcard_origins.extend(
            _wildcard_origins_from_statement(
                node, module=module, is_package_init=is_package_init
            )
        )
    return ModuleNamespace(
        module=module,
        bindings=tuple(bindings.items()),
        all_names=_literal_all_names(tree),
        wildcard_origins=tuple(dict.fromkeys(wildcard_origins)),
    )


def _bindings_from_statement(
    node: ast.stmt, *, module: str, is_package_init: bool
) -> tuple[tuple[str, Binding], ...]:
    """Return the names one top-level statement binds."""
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return ((node.name, Definition()),)
    if isinstance(node, ast.Assign):
        return tuple(
            (name, Definition())
            for target in node.targets
            for name in _assigned_names(target)
        )
    if isinstance(node, ast.AnnAssign):
        name = _annotated_target_name(node)
        return () if name is None else ((name, Definition()),)
    if isinstance(node, ast.Import):
        return _direct_import_bindings(node)
    if isinstance(node, ast.ImportFrom):
        return _from_import_bindings(
            node, module=module, is_package_init=is_package_init
        )
    return ()


def _assigned_names(target: ast.expr) -> tuple[str, ...]:
    """Return every name an assignment target binds.

    Unpacking targets bind each element, so ``First, Second = ...`` binds both
    names and ``[a, *rest] = ...`` binds both of those. Reading only a bare
    ``ast.Name`` target would miss those bindings entirely.
    """
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Starred):
        return _assigned_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return tuple(
            name for element in target.elts for name in _assigned_names(element)
        )
    return ()


def _annotated_target_name(node: ast.AnnAssign) -> str | None:
    """Return the name an annotated assignment binds, if it binds one."""
    target = node.target
    if node.value is None or not isinstance(target, ast.Name):
        return None
    return target.id


def _direct_import_bindings(node: ast.Import) -> tuple[tuple[str, Binding], ...]:
    """Return bindings for ``import a.b``.

    Without an ``as`` clause Python binds the *leading* name: ``import a.b``
    makes ``a`` available, and ``a.b`` is reached as an attribute of it. So the
    bound name and its origin are both the leading component. With ``as``, the
    chosen name is bound directly to the full dotted module instead.
    """
    return tuple(_direct_import_binding(alias) for alias in node.names)


def _direct_import_binding(alias: ast.alias) -> tuple[str, Binding]:
    if alias.asname is not None:
        return (alias.asname, Imported(origin=alias.name, symbol=None))
    leading = alias.name.split(".", maxsplit=1)[0]
    return (leading, Imported(origin=leading, symbol=None))


def _from_import_bindings(
    node: ast.ImportFrom, *, module: str, is_package_init: bool
) -> tuple[tuple[str, Binding], ...]:
    """Return bindings for ``from target import names``.

    Wildcard entries bind no single name here; they are reported separately by
    :func:`_wildcard_origins_from_statement` because their effect depends on the
    origin module's own wildcard export set.
    """
    target = _resolve_from(node, module=module, is_package_init=is_package_init)
    if target is None:
        return ()
    return tuple(
        (
            alias.asname or alias.name,
            Imported(origin=target, symbol=alias.name),
        )
        for alias in node.names
        if alias.name != "*"
    )


def _wildcard_origins_from_statement(
    node: ast.stmt, *, module: str, is_package_init: bool
) -> tuple[str, ...]:
    """Return modules pulled into this namespace by ``from origin import *``."""
    if not isinstance(node, ast.ImportFrom):
        return ()
    if not any(alias.name == "*" for alias in node.names):
        return ()
    target = _resolve_from(node, module=module, is_package_init=is_package_init)
    return () if target is None else (target,)


def _resolve_from(
    node: ast.ImportFrom, *, module: str, is_package_init: bool
) -> str | None:
    return resolve_import_from(
        module,
        is_package_init=is_package_init,
        level=node.level,
        imported_module=node.module,
    )


def _literal_all_names(tree: ast.Module) -> tuple[str, ...] | None:
    """Return the names the module's ``__all__`` ends up holding, if knowable.

    A plain assignment replaces the sequence outright, while an augmented
    assignment extends whatever the sequence held before. An operation Hecate
    cannot evaluate leaves the sequence unknown, which the caller reads as
    "fall back to the default public-name rule" rather than as emptiness.

    An ``__all__`` assigned inside a control-flow block is conditional, so which
    branch ran decides the result. Hecate cannot evaluate the condition, so it
    treats such an assignment as making the sequence unknowable rather than
    guessing from source order.
    """
    names: tuple[str, ...] | None = None
    for node, is_nested in module_level_statements(tree.body):
        assignment = _all_assignment(node)
        if assignment is None:
            continue
        if is_nested:
            return None
        names = _apply_all_assignment(assignment, names=names)
    return names


def _apply_all_assignment(
    assignment: tuple[bool, ast.expr | None], *, names: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    """Return the ``__all__`` sequence after one assignment statement.

    ``names`` is the sequence beforehand, or ``None`` when it is not statically
    known. A ``None`` result means the sequence stays, or becomes, unknowable.
    """
    is_augmented, value = assignment
    if value is None:
        return names
    additions = _literal_string_sequence(value)
    if additions is None:
        return None
    if is_augmented:
        # ``__all__ += [...]`` extends; it only stays knowable if it started
        # knowable, since the prefix is whatever the earlier value held.
        return None if names is None else (*names, *additions)
    return additions


def _all_assignment(node: ast.stmt) -> tuple[bool, ast.expr | None] | None:
    """Return ``(is_augmented, value)`` when ``node`` assigns to ``__all__``.

    ``value`` is ``None`` for an augmented assignment with a non-list operand,
    which cannot extend the sequence and so clears any known value.
    """
    if isinstance(node, ast.Assign) and _assigns_all(node.targets):
        return (False, node.value)
    if isinstance(node, ast.AnnAssign) and _target_is_all(node.target):
        return (False, node.value)
    if isinstance(node, ast.AugAssign) and _target_is_all(node.target):
        return (True, node.value)
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
