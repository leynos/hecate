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
model by :mod:`hecate.origins` and :mod:`hecate.policy` respectively. Reading
the ``__all__`` sequence itself is :mod:`hecate.all_sequence`, which this module
consults for the wildcard selection.
"""

from __future__ import annotations

import ast
import dataclasses as dc
import typing as typ

from .all_sequence import literal_all_names
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
    """Module-level bindings in source order.

    A name may appear more than once. A binding written unconditionally
    replaces every earlier candidate for its name, because no path through the
    module can reach them; a binding inside a control-flow block only adds a
    candidate, because which branch runs decides the name's value. Both are
    recorded so provenance can report every origin a name may hold.
    """

    all_names: tuple[str, ...] | None = None
    """Names from the last literal ``__all__`` assignment, or ``None``."""

    wildcard_origins: tuple[str, ...] = ()
    """Modules this one pulls in with ``from origin import *``."""

    @property
    def has_explicit_all(self) -> bool:
        """Return whether a literal ``__all__`` assignment was found."""
        return self.all_names is not None

    @property
    def bound_names(self) -> frozenset[str]:
        """Return every name the module binds, in any way."""
        return frozenset(name for name, _ in self.bindings)

    def bindings_for(self, name: str) -> tuple[Binding, ...]:
        """Return every binding ``name`` may hold, in source order.

        More than one entry means the name's value depends on which branch of
        the module ran, so each entry is a distinct possible origin rather than
        a superseded one.
        """
        return tuple(binding for bound, binding in self.bindings if bound == name)


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
    bindings: list[tuple[str, Binding]] = []
    wildcard_origins: list[str] = []
    for node, is_nested in module_level_statements(tree.body):
        found = _bindings_from_statement(
            node, module=module, is_package_init=is_package_init
        )
        if is_nested or _binds_conditionally(node):
            # A conditional binding adds a candidate; it cannot displace an
            # earlier binding, because the branch may not have run.
            bindings.extend(found)
        else:
            # An unconditional binding runs on every path, so it supersedes
            # every earlier candidate for the names it binds.
            _supersede(bindings, {name for name, _ in found})
            bindings.extend(found)
        wildcard_origins.extend(
            _wildcard_origins_from_statement(
                node, module=module, is_package_init=is_package_init
            )
        )
    return ModuleNamespace(
        module=module,
        bindings=tuple(bindings),
        all_names=literal_all_names(tree),
        wildcard_origins=tuple(dict.fromkeys(wildcard_origins)),
    )


def _supersede(bindings: list[tuple[str, Binding]], names: set[str]) -> None:
    """Drop every earlier candidate for ``names``, in place.

    Used for an unconditional binding, which no earlier candidate can survive
    on any execution path.
    """
    bindings[:] = [(name, binding) for name, binding in bindings if name not in names]


def _binds_conditionally(node: ast.stmt) -> bool:
    """Return whether a module-level statement binds only if it runs to completion.

    A ``for`` target is bound once per iteration, so an empty iterable leaves
    the name unbound. The statement sits at module level, but the binding it
    makes is as conditional as one written inside an ``if``.
    """
    return isinstance(node, ast.For | ast.AsyncFor)


def _bindings_from_statement(
    node: ast.stmt, *, module: str, is_package_init: bool
) -> tuple[tuple[str, Binding], ...]:
    """Return the names one module-scope statement binds.

    ``import`` forms need the module context to resolve their origin, so they
    are handled here; every other statement binds plain definitions, which
    :func:`_defined_names` covers.
    """
    match node:
        case ast.Import():
            return _direct_import_bindings(node)
        case ast.ImportFrom():
            return _from_import_bindings(
                node, module=module, is_package_init=is_package_init
            )
        case _:
            return tuple((name, Definition()) for name in _defined_names(node))


def _defined_names(node: ast.stmt) -> tuple[str, ...]:
    """Return the names a non-import statement defines at module scope.

    Every form here runs at import time and binds module attributes. Type
    aliases, loop targets and ``with`` targets are easy to overlook because
    they do not look like assignments, but a name they bind is as reachable by
    ``from module import name`` as any other.
    """
    names: tuple[str, ...] = ()
    match node:
        case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
            names = (node.name,)
        case ast.TypeAlias():
            names = _assigned_names(node.name)
        case ast.Assign():
            names = tuple(
                name for target in node.targets for name in _assigned_names(target)
            )
        case ast.AnnAssign():
            name = _annotated_target_name(node)
            names = () if name is None else (name,)
        case ast.For() | ast.AsyncFor():
            names = _assigned_names(node.target)
        case ast.With() | ast.AsyncWith():
            names = tuple(
                name
                for item in node.items
                if item.optional_vars is not None
                for name in _assigned_names(item.optional_vars)
            )
    return names


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
