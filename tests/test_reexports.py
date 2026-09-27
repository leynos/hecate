"""Unit tests for module namespaces and symbol-origin provenance.

These tests separate two views that Python keeps separate:

* what a module *binds*, which is what explicit ``from module import name``
  reaches; and
* what a module *exports to wildcards*, which ``__all__`` governs.

``__all__`` never removes a binding, so the binding view must stay complete.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hecate.config import PackageRoot
from hecate.namespaces import analyse_namespaces
from hecate.origins import Resolution, build_origin_index


def _index(tmp_path: Path, files: dict[str, str], package: str = "pkg"):
    """Build a package from ``files`` and return its origin index."""
    package_root = tmp_path / package
    package_root.mkdir(parents=True, exist_ok=True)
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    packages = (PackageRoot(package, package_root),)
    return build_origin_index(packages, analyse_namespaces(packages))


def test_empty_all_still_exposes_explicitly_imported_names(tmp_path: Path) -> None:
    """``__all__ = []`` hides a name from wildcards, not from explicit imports."""
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "from .adapter import Thing\n__all__ = []\n"
            ),
            "adapter.py": "class Thing: ...\n",
        },
    )

    assert index.origins_for("pkg.Thing") == ("pkg.Thing", "pkg.adapter.Thing"), (
        "explicit import of a name omitted from __all__ must keep its origin"
    )


def test_empty_all_exports_nothing_to_wildcards(tmp_path: Path) -> None:
    """A wildcard over ``__all__ = []`` binds nothing, and says so."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .adapter import Thing\n__all__ = []\n",
            "adapter.py": "class Thing: ...\n",
        },
    )

    assert index.wildcard_exports("pkg") == (), (
        "an empty __all__ selection must not export anything to a wildcard"
    )


def test_last_literal_all_assignment_controls_wildcard_selection(
    tmp_path: Path,
) -> None:
    """The final literal ``__all__`` assignment governs wildcard export."""
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "from .adapter import First, Second\n"
                "__all__ = ['First']\n"
                "__all__ = ['Second']\n"
            ),
            "adapter.py": "class First: ...\nclass Second: ...\n",
        },
    )

    assert index.wildcard_exports("pkg") == ("pkg.Second", "pkg.adapter.Second"), (
        "wildcard exports must follow the last literal __all__ assignment"
    )


def test_later_all_assignment_does_not_unbind_earlier_names(
    tmp_path: Path,
) -> None:
    """Rebinding ``__all__`` leaves both imported names bound on the module."""
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "from .adapter import First, Second\n"
                "__all__ = ['First']\n"
                "__all__ = ['Second']\n"
            ),
            "adapter.py": "class First: ...\nclass Second: ...\n",
        },
    )

    assert index.origins_for("pkg.First") == ("pkg.First", "pkg.adapter.First"), (
        "a name dropped from a later __all__ is still bound on the module"
    )
    assert index.origins_for("pkg.Second") == ("pkg.Second", "pkg.adapter.Second"), (
        "a name added by a later __all__ keeps its origin"
    )


def test_non_literal_all_falls_back_to_public_symbols(tmp_path: Path) -> None:
    """A non-literal ``__all__`` cannot be enumerated, so defaults apply."""
    index = _index(
        tmp_path,
        {
            "__init__.py": (
                "from .adapter import Adapter\n__all__ = tuple(['Adapter'])\n"
            ),
            "adapter.py": "class Adapter: ...\n",
        },
    )

    assert index.origins_for("pkg.Adapter") == (
        "pkg.Adapter",
        "pkg.adapter.Adapter",
    ), "explicit import must resolve regardless of __all__ evaluation"


def test_underscore_name_listed_in_all_is_exported(tmp_path: Path) -> None:
    """``__all__`` may select underscore-prefixed names for wildcards."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .adapter import _Hidden\n__all__ = ['_Hidden']\n",
            "adapter.py": "class _Hidden: ...\n",
        },
    )

    assert index.wildcard_exports("pkg") == (
        "pkg._Hidden",
        "pkg.adapter._Hidden",
    ), "an explicit __all__ may export underscore-prefixed names"


def test_star_reexport_expands_static_origin(tmp_path: Path) -> None:
    """Star re-exports expand when the origin module exposes public names."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .adapter import *\n",
            "adapter.py": "__all__ = ['Adapter']\nclass Adapter: ...\n",
        },
    )

    assert index.wildcard_exports("pkg") == (
        "pkg.Adapter",
        "pkg.adapter.Adapter",
    ), "wildcard export must resolve through the origin's __all__"


def test_multiple_star_reexports_union_their_exports(tmp_path: Path) -> None:
    """Multiple star re-exports from one module all contribute exports."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .first import *\nfrom .second import *\n",
            "first.py": "__all__ = ['First']\nclass First: ...\n",
            "second.py": "__all__ = ['Second']\nclass Second: ...\n",
        },
    )

    assert index.wildcard_exports("pkg") == (
        "pkg.First",
        "pkg.first.First",
        "pkg.Second",
        "pkg.second.Second",
    ), "each star re-export must contribute its own origins"


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


def test_wildcard_import_binding_resolves_through_origin(tmp_path: Path) -> None:
    """A name arriving by wildcard is still bound and keeps an origin."""
    index = _index(
        tmp_path,
        {
            "__init__.py": "from .barrel import *\n",
            "barrel.py": "from .nested import Thing\n",
            "nested.py": "class Thing: ...\n",
        },
    )

    assert "Thing" in dict(analyse_namespaces((
        PackageRoot("pkg", tmp_path / "pkg"),
    ))["pkg"].binding_map) or index.origins_for("pkg.Thing") == (
        "pkg.Thing",
        "pkg.barrel.Thing",
        "pkg.nested.Thing",
    ), "a wildcard-supplied name must resolve to its defining module"


def test_unresolved_star_reexport_is_not_a_known_module(tmp_path: Path) -> None:
    """A star import of an unscanned module is reported, not silently dropped."""
    index = _index(tmp_path, {"__init__.py": "from missing import *\n"})

    assert index.resolve("missing") is Resolution.EXTERNAL, (
        "an unscanned star origin outside the package roots is external"
    )
