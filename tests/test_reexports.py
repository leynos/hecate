"""Unit tests for static package-barrel re-export expansion."""

from __future__ import annotations

from pathlib import Path

from hecate.config import PackageRoot
from hecate.reexports import build_reexport_index


def test_explicit_all_uses_last_literal_assignment(tmp_path: Path) -> None:
    """The final literal ``__all__`` assignment controls exported names."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import First, Second\n"
        "__all__ = ['First']\n"
        "__all__ = ['Second']\n",
        encoding="utf-8",
    )
    (package_root / "adapter.py").write_text(
        "class First: ...\nclass Second: ...\n", encoding="utf-8"
    )

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.Second") == (
        "pkg.Second",
        "pkg.adapter.Second",
    ), "expand_import('pkg.Second') returned unexpected explicit __all__ result"
    assert index.expand_import("pkg.First") == ("pkg.First",), (
        "expand_import('pkg.First') should not include a stale __all__ export"
    )


def test_unresolved_all_falls_back_to_public_symbols(tmp_path: Path) -> None:
    """Non-literal ``__all__`` falls back to public imported symbols."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import Adapter\n__all__ = tuple(['Adapter'])\n",
        encoding="utf-8",
    )
    (package_root / "adapter.py").write_text("class Adapter: ...\n", encoding="utf-8")

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.Adapter") == (
        "pkg.Adapter",
        "pkg.adapter.Adapter",
    ), "expand_import('pkg.Adapter') returned unexpected fallback export"


def test_star_reexport_expands_static_origin(tmp_path: Path) -> None:
    """Star re-exports expand when the origin module exposes public names."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import *\n", encoding="utf-8"
    )
    (package_root / "adapter.py").write_text(
        "__all__ = ['Adapter']\nclass Adapter: ...\n", encoding="utf-8"
    )

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.Adapter") == (
        "pkg.Adapter",
        "pkg.adapter.Adapter",
    ), "expand_import('pkg.Adapter') returned unexpected star export"


def test_multiple_star_reexports_preserve_all_origins(tmp_path: Path) -> None:
    """Multiple star re-exports from one module are all indexed."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .first import *\nfrom .second import *\n",
        encoding="utf-8",
    )
    (package_root / "first.py").write_text(
        "__all__ = ['First']\nclass First: ...\n",
        encoding="utf-8",
    )
    (package_root / "second.py").write_text(
        "__all__ = ['Second']\nclass Second: ...\n",
        encoding="utf-8",
    )

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.First") == (
        "pkg.First",
        "pkg.first.First",
    ), "expand_import('pkg.First') returned unexpected first star origin"
    assert index.expand_import("pkg.Second") == (
        "pkg.Second",
        "pkg.second.Second",
    ), "expand_import('pkg.Second') returned unexpected second star origin"


def test_star_reexport_flattens_transitive_wildcard_origin(tmp_path: Path) -> None:
    """Star re-export chains flatten to concrete symbols."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .barrel import *\n",
        encoding="utf-8",
    )
    (package_root / "barrel.py").write_text(
        "from .nested import *\n",
        encoding="utf-8",
    )
    (package_root / "nested.py").write_text(
        "__all__ = ['Thing']\nclass Thing: ...\n",
        encoding="utf-8",
    )

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.Thing") == (
        "pkg.Thing",
        "pkg.nested.Thing",
    ), "expand_import('pkg.Thing') returned unexpected transitive star origin"


def test_unresolved_star_reexport_is_not_indexed(tmp_path: Path) -> None:
    """Unresolved wildcard origins are dropped instead of indexed as ``*``."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from missing import *\n",
        encoding="utf-8",
    )

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert "pkg.*" not in index.exports, (
        f"expected unresolved wildcard to be absent, got {index.exports!r}"
    )
    assert index.expand_import("pkg.*") == ("pkg.*",), (
        "expand_import('pkg.*') should return only the unresolved wildcard"
    )


def test_chained_reexport_expands_transitive_origin(tmp_path: Path) -> None:
    """Package barrels expand through intermediate package barrels."""
    package_root = tmp_path / "pkg"
    adapters_root = package_root / "adapters"
    outbound_root = adapters_root / "outbound"
    outbound_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text(
        "from .adapters import db\n__all__ = ['db']\n",
        encoding="utf-8",
    )
    (adapters_root / "__init__.py").write_text(
        "from .outbound import db\n__all__ = ['db']\n",
        encoding="utf-8",
    )
    (outbound_root / "__init__.py").write_text(
        "from . import db\n__all__ = ['db']\n",
        encoding="utf-8",
    )
    (outbound_root / "db.py").write_text("class Database: ...\n", encoding="utf-8")

    index = build_reexport_index((PackageRoot("pkg", package_root),))

    assert index.expand_import("pkg.db") == (
        "pkg.db",
        "pkg.adapters.db",
        "pkg.adapters.outbound.db",
    ), "expand_import('pkg.db') returned unexpected chained package-barrel origins"
