"""Unit tests for what a module binds.

Python keeps two views of a module separate, and this file covers the first:
what a module *binds*, which is what explicit ``from module import name``
reaches. ``__all__`` never removes a binding, so the binding view must stay
complete and must record every origin a name may hold.

Wildcard export selection, which ``__all__`` does govern, is covered in
``test_reexports.py``.
"""

from __future__ import annotations

from pathlib import Path

from hecate.config import PackageRoot
from hecate.namespaces import analyse_namespaces
from hecate.origins import OriginIndex, build_origin_index


def _packages(
    tmp_path: Path, files: dict[str, str], package: str = "pkg"
) -> tuple[PackageRoot, ...]:
    """Write a package from ``files`` and return its package root."""
    package_root = tmp_path / package
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return (PackageRoot(package, package_root),)


def _index(tmp_path: Path, files: dict[str, str], package: str = "pkg") -> OriginIndex:
    """Build a package from ``files`` and return its origin index."""
    packages = _packages(tmp_path, files, package=package)
    return build_origin_index(packages, analyse_namespaces(packages))


def test_later_named_reexport_shadows_earlier_origin(tmp_path: Path) -> None:
    """Duplicate named imports follow Python's last-binding semantics."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .first import Thing\nfrom .second import Thing\n",
            "first.py": "class Thing: ...\n",
            "second.py": "class Thing: ...\n",
        },
    )

    assert index.origins_for("pkg.Thing") == ("pkg.Thing", "pkg.second.Thing"), (
        "the final named import must win when a name is rebound"
    )


def test_branches_binding_one_name_keep_every_origin(tmp_path: Path) -> None:
    """A name bound in two branches may hold either branch's origin.

    Which branch runs is a runtime decision, so both are reachable and both
    belong in the provenance chain. Keeping only the syntactically last one
    would let a forbidden origin go unreported whenever the allowed branch
    happened to be written second.
    """
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "if True:\n"
                "    from .adapter import Thing\n"
                "else:\n"
                "    from .other import Thing\n"
            ),
            "adapter.py": "class Thing: ...\n",
            "other.py": "class Thing: ...\n",
        },
    )

    assert index.origins_for("pkg.Thing") == (
        "pkg.Thing",
        "pkg.adapter.Thing",
        "pkg.other.Thing",
    ), "every branch-supplied origin must stay reachable"


def test_conditional_rebinding_keeps_the_earlier_origin(tmp_path: Path) -> None:
    """A conditional rebinding adds an origin instead of replacing one.

    The unconditional import still runs on every path, so its origin is
    reachable whenever the branch does not. Treating the conditional statement
    as the last word would drop a reachable origin entirely.
    """
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "from .adapter import Thing\nif True:\n    from .other import Thing\n"
            ),
            "adapter.py": "class Thing: ...\n",
            "other.py": "class Thing: ...\n",
        },
    )

    assert index.origins_for("pkg.Thing") == (
        "pkg.Thing",
        "pkg.adapter.Thing",
        "pkg.other.Thing",
    ), "a conditional rebinding must not displace the unconditional binding"


def test_unconditional_rebinding_after_a_branch_replaces_it(tmp_path: Path) -> None:
    """A later unconditional statement settles the name's origin.

    Every path through the module runs the unconditional import, so it is the
    only origin left by the time the module finishes executing. Keeping the
    branch-supplied origin as well would report a dependency that cannot
    actually exist.
    """
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "if True:\n    from .other import Thing\nfrom .adapter import Thing\n"
            ),
            "adapter.py": "class Thing: ...\n",
            "other.py": "class Thing: ...\n",
        },
    )

    assert index.origins_for("pkg.Thing") == ("pkg.Thing", "pkg.adapter.Thing"), (
        "an unconditional rebinding must supersede the branch alternatives"
    )


def test_type_alias_is_a_module_binding(tmp_path: Path) -> None:
    """A ``type`` statement binds a module attribute like any other name.

    ``type UserId = int`` executes at import time and binds ``UserId`` on the
    module, so an explicit import of it resolves and a wildcard exports it.
    Missing the binding would report a valid internal import as unresolved.
    """
    index = _index(
        tmp_path,
        {
            "__init__.py": "",
            "types.py": "type UserId = int\n",
        },
    )

    assert index.origins_for("pkg.types.UserId") == ("pkg.types.UserId",), (
        "a type alias must be a binding an explicit import can reach"
    )
    assert index.wildcard_exports("pkg.types") == ("pkg.types.UserId",), (
        "a public type alias must be exported to wildcards"
    )


def test_loop_and_with_targets_are_module_bindings(tmp_path: Path) -> None:
    """``for`` and ``with`` targets bind module attributes at import time.

    Both statements run at module scope, so the names they bind are reachable by
    ``from module import name``. Reading only assignment statements would miss
    them and report a valid internal import as unresolved.
    """
    packages = _packages(
        tmp_path,
        {
            "__init__.py": "",
            "m.py": (
                "import contextlib\n"
                "for Loop in (1,):\n"
                "    pass\n"
                "with contextlib.suppress(Exception) as Entered:\n"
                "    pass\n"
            ),
        },
    )
    namespaces = analyse_namespaces(packages)

    assert {"Loop", "Entered"} <= namespaces["pkg.m"].bound_names, (
        f"loop and with targets must bind: {namespaces['pkg.m'].bindings!r}"
    )


def test_bare_dotted_import_originates_at_its_leading_package(
    tmp_path: Path,
) -> None:
    """``import a.b`` binds ``a``, so the name's origin is ``a``.

    Python binds the leading component, and reaches ``a.b`` as an attribute of
    it. Recording ``a.b`` as the origin of the name ``a`` would attribute the
    binding to a module the name does not refer to.
    """
    index = _index(
        tmp_path,
        {"__init__.py": "import os.path\nimport json.decoder as dec\n"},
    )

    assert index.origins_for("pkg.os") == ("pkg.os", "os"), (
        "an unaliased dotted import must originate at its leading package"
    )
    assert index.origins_for("pkg.dec") == ("pkg.dec", "json.decoder"), (
        "an aliased dotted import keeps the full module as its origin"
    )


def test_unpacking_assignment_binds_every_name(tmp_path: Path) -> None:
    """Tuple, list, and starred targets each bind their names.

    Only the binding view is needed here, so the namespace model is read
    directly rather than through the origin index.
    """
    packages = _packages(
        tmp_path,
        {
            "__init__.py": "",
            "m.py": "First, Second = 1, 2\n[a, *rest] = [3, 4, 5]\n",
        },
    )
    namespaces = analyse_namespaces(packages)

    assert namespaces["pkg.m"].bound_names == {"First", "Second", "a", "rest"}, (
        f"unpacking must bind every target: {namespaces['pkg.m'].bindings!r}"
    )
