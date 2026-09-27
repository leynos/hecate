"""Unit tests for what a module executes when it is imported.

A module-level ``if``, ``try``, loop, or ``with`` still runs its body at import
time, so a binding or import inside one is a real part of the module's
behaviour. Only function and class bodies are local. These tests pin that
distinction, plus the ``__all__`` consequence it carries: a sequence assigned
inside a branch is conditional, so which value it ends up holding is a runtime
decision rather than something source order can settle.
"""

from __future__ import annotations

from pathlib import Path

from hecate.config import PackageRoot
from hecate.namespaces import ModuleNamespace, analyse_namespaces


def _analyse(
    tmp_path: Path, files: dict[str, str], package: str = "pkg"
) -> dict[str, ModuleNamespace]:
    """Build a package from ``files`` and return its analysed namespaces."""
    package_root = tmp_path / package
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return analyse_namespaces((PackageRoot(package, package_root),))


def test_import_inside_module_level_if_is_seen(tmp_path: Path) -> None:
    """A binding inside a module-level ``if`` still runs at import time.

    Conditional imports are ordinary in compatibility shims, so a namespace
    model that read only top-level statements would miss them.
    """
    namespaces = _analyse(
        tmp_path,
        {
            "__init__.py": "",
            "m.py": "if True:\n    from . import other\n",
            "other.py": "",
        },
    )

    assert set(namespaces["pkg.m"].binding_map) == {"other"}, (
        f"a conditional import must still bind: {namespaces['pkg.m'].bindings!r}"
    )


def test_import_inside_module_level_try_is_seen(tmp_path: Path) -> None:
    """Names bound in a ``try``/``except`` block count at module scope.

    The handler binds nothing, so ``other`` is present only because the ``try``
    body was read rather than skipped.
    """
    namespaces = _analyse(
        tmp_path,
        {
            "__init__.py": "",
            "m.py": "try:\n    from . import other\nexcept ImportError:\n    pass\n",
            "other.py": "",
        },
    )

    assert set(namespaces["pkg.m"].binding_map) == {"other"}, (
        f"a try/except binding must be visible: {namespaces['pkg.m'].bindings!r}"
    )


def test_wildcard_inside_module_level_if_is_seen(tmp_path: Path) -> None:
    """A conditional star import still contributes to the export set."""
    namespaces = _analyse(
        tmp_path,
        {
            "__init__.py": "if True:\n    from .barrel import *\n",
            "barrel.py": "",
        },
    )

    assert namespaces["pkg"].wildcard_origins == ("pkg.barrel",), (
        f"a conditional star origin must be recorded: "
        f"{namespaces['pkg'].wildcard_origins!r}"
    )


def test_conditional_all_is_treated_as_unknowable(tmp_path: Path) -> None:
    """An ``__all__`` set inside a branch cannot be pinned to one value.

    Which branch runs is a runtime decision, so claiming either value would be
    a guess. Falling back to the default public-name rule is the honest read.

    The fixture also carries an unconditional assignment, so the test fails if
    the conditional one is simply not seen: reading only top-level statements
    would report the unconditional value instead of admitting ignorance.
    """
    namespaces = _analyse(
        tmp_path,
        {
            "__init__.py": (
                "__all__ = ['Adapter']\n"
                "try:\n"
                "    __all__ = ['Thing']\n"
                "except Exception:\n"
                "    pass\n"
            ),
            "adapter.py": "class Adapter: ...\nclass Thing: ...\n",
        },
    )

    assert namespaces["pkg"].all_names is None, (
        f"a branch-dependent __all__ must stay unknowable, "
        f"got {namespaces['pkg'].all_names!r}"
    )
