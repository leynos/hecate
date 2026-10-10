"""Static evaluation of a module's ``__all__`` sequence.

``__all__`` decides which names a wildcard import picks up, so getting its
final value right decides whether a wildcard consumer sees a forbidden origin
or not. Reading the sequence statically is its own problem: it needs the module
scope traversal from :mod:`hecate.module_scope`, but none of the namespace or
provenance machinery, so it lives here.

The evaluator follows the operations it can read exactly and reports ``None``
for anything else. ``None`` means "unknowable", which the caller turns into the
default public-name rule; it never means "empty", because an empty selection is
a real, meaningful ``__all__ = []``.
"""

from __future__ import annotations

import ast

from .module_scope import module_level_statements


def literal_all_names(tree: ast.Module) -> tuple[str, ...] | None:
    """Return the names the module's ``__all__`` ends up holding, if knowable.

    A plain assignment replaces the sequence outright, while an augmented
    assignment extends whatever the sequence held before. An operation Hecate
    cannot evaluate leaves the sequence unknown, which the caller reads as
    "fall back to the default public-name rule" rather than as emptiness.

    An ``__all__`` assigned inside a control-flow block is conditional, so which
    branch ran decides the result, and such an assignment leaves the sequence
    unknowable. The walk continues past it rather than stopping, because a
    later assignment written at module level runs on every import and so
    deterministically replaces every branch result with a knowable value.
    """
    names: tuple[str, ...] | None = None
    for node, is_nested in module_level_statements(tree.body):
        assignment = _all_assignment(node)
        if assignment is None:
            if _obscures_all(node):
                # The statement changes the sequence in a way the evaluator
                # cannot follow, so the selection is unknowable from here.
                names = None
            continue
        names = _apply_all_assignment(assignment, names=names, is_conditional=is_nested)
    return names


def _apply_all_assignment(
    assignment: tuple[bool, ast.expr | None],
    *,
    names: tuple[str, ...] | None,
    is_conditional: bool,
) -> tuple[str, ...] | None:
    """Return the ``__all__`` sequence after one assignment statement.

    ``names`` is the sequence beforehand, or ``None`` when it is not statically
    known. ``is_conditional`` marks an assignment written inside a control-flow
    block, which may not have run at all. A ``None`` result means the sequence
    stays, or becomes, unknowable.
    """
    is_augmented, value = assignment
    if value is None:
        # ``__all__: list[str]`` declares without binding, so an annotated
        # assignment without a value leaves the sequence exactly as it was.
        return names
    additions = _literal_string_sequence(value)
    if additions is None:
        return None
    if is_conditional:
        # Which branch ran decides the value, so neither the earlier sequence
        # nor this one can be pinned.
        return None
    if is_augmented:
        # ``__all__ += [...]`` extends; it only stays knowable if it started
        # knowable, since the prefix is whatever the earlier value held.
        return None if names is None else (*names, *additions)
    return additions


def _all_assignment(node: ast.stmt) -> tuple[bool, ast.expr | None] | None:
    """Return ``(is_augmented, value)`` when ``node`` assigns to ``__all__``.

    ``value`` is ``None`` only for an annotated assignment without a value,
    such as ``__all__: list[str]``, which binds nothing and so cannot change
    the sequence. An augmented assignment always carries a value.
    """
    if isinstance(node, ast.Assign) and _assigns_all(node.targets):
        return (False, node.value)
    if isinstance(node, ast.AnnAssign) and _target_is_all(node.target):
        return (False, node.value)
    if isinstance(node, ast.AugAssign) and _target_is_all(node.target):
        return (True, node.value)
    return None


def _obscures_all(node: ast.stmt) -> bool:
    """Return whether ``node`` changes ``__all__`` in a way the walk cannot read.

    Three spellings defeat the literal evaluator. A method call such as
    ``__all__.extend(...)`` and a subscript store such as ``__all__[0] = ...``
    rewrite the sequence in place, so the last literal assignment the walk saw
    no longer describes what the module exports. An unpacking target such as
    ``__all__, flag = ['Adapter'], True`` binds the sequence through a form the
    evaluator does not follow.

    Each leaves the selection unknowable, so the walk marks it unknown rather
    than keeping a stale literal value that could hide an exported name.
    """
    match node:
        case ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id="__all__")))):
            return True
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            return any(_touches_all(target) for target in targets)
        case _:
            return False


def _touches_all(target: ast.expr) -> bool:
    """Return whether an assignment target binds or indexes into ``__all__``."""
    match target:
        case ast.Name(id="__all__"):
            return True
        case ast.Subscript(value=value):
            return _touches_all(value)
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            return any(_touches_all(element) for element in elts)
        case ast.Starred(value=value):
            return _touches_all(value)
        case _:
            return False


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
