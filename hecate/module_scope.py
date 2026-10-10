"""Traversal of the statements that run at module scope.

A module-level ``if``, ``try``, loop, ``with``, or ``match`` still executes its
body at import time, so a binding or import inside one is a real part of the
module's behaviour. Reading only the top level would miss those entirely.

This is deliberately separate from :mod:`hecate.namespaces`: deciding *which*
statements run at module scope is a question about the syntax tree, while
deciding what those statements bind is a question about the module's namespace.
Keeping them apart lets the namespace model read as policy rather than as tree
walking.
"""

from __future__ import annotations

import ast
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

#: Nodes whose bodies run in their own local scope. Names bound inside them are
#: not module attributes, and imports inside them are not module imports, so the
#: traversal stops here.
_LOCAL_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def module_level_statements(
    body: list[ast.stmt],
) -> cabc.Iterator[tuple[ast.stmt, bool]]:
    """Yield every statement that runs at module scope, with a nesting flag.

    The flag is ``False`` for a statement written directly at module level and
    ``True`` for one nested inside a control-flow block. Callers that need to
    reason about execution order, such as ``__all__``, use it to tell an
    unconditional statement from a conditional one.
    """
    for node in body:
        yield node, False
        yield from _nested_module_statements(node)


def _nested_module_statements(node: ast.stmt) -> cabc.Iterator[tuple[ast.stmt, bool]]:
    if isinstance(node, _LOCAL_SCOPE_NODES):
        return
    for child in _direct_bodies(node):
        for nested, _ in module_level_statements([child]):
            yield nested, True


def _direct_bodies(node: ast.stmt) -> list[ast.stmt]:
    """Return the statements nested one level inside ``node``."""
    return [statement for suite in _nested_suites(node) for statement in suite]


def _nested_suites(node: ast.stmt) -> tuple[list[ast.stmt], ...]:
    """Return the statement suites nested one level inside ``node``.

    Every suite a compound statement can run is a separate entry, so the
    flattening happens once in :func:`_direct_bodies` rather than once per
    statement kind. Suites that cannot run statements, such as a ``try``
    without handlers, contribute nothing.
    """
    if isinstance(node, ast.If | ast.For | ast.AsyncFor | ast.While):
        return (node.body, node.orelse)
    if isinstance(node, ast.Try | ast.TryStar):
        return _try_suites(node)
    if isinstance(node, ast.With | ast.AsyncWith):
        return (node.body,)
    if isinstance(node, ast.Match):
        return _case_suites(node)
    return ()


def _try_suites(node: ast.Try | ast.TryStar) -> tuple[list[ast.stmt], ...]:
    """Return every suite a ``try`` statement can execute."""
    handler_suites = [handler.body for handler in node.handlers]
    return (node.body, node.orelse, node.finalbody, *handler_suites)


def _case_suites(node: ast.Match) -> tuple[list[ast.stmt], ...]:
    """Return the body of each ``case`` in a ``match`` statement."""
    return tuple(case.body for case in node.cases)
