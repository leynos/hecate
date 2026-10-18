"""Unit tests for AST import collection helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hecate.imports import (
    DiscoveryError,
    collect_import_statements,
    compute_module_name,
    discover_modules,
    relative_import_base,
)


def test_compute_module_name_handles_package_init() -> None:
    """Package ``__init__`` files map to the package module."""
    assert compute_module_name(Path("pkg"), "pkg", Path("pkg/__init__.py")) == "pkg"


def test_compute_module_name_handles_nested_module() -> None:
    """Nested source paths map to dotted module names."""
    module = compute_module_name(Path("pkg"), "pkg", Path("pkg/application/service.py"))
    assert module == "pkg.application.service"


def test_discover_modules_pairs_each_file_with_its_dotted_name(
    tmp_path: Path,
) -> None:
    """Every ``*.py`` file under the root comes back with its module name.

    This is the single walk the edge pass and the module pass both read, so the
    pairing it produces is what keeps them from disagreeing about which files
    exist or what they are called.
    """
    package_root = tmp_path / "pkg"
    (package_root / "domain").mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "model.py").write_text("", encoding="utf-8")

    discovery = discover_modules(package_root, "pkg")

    assert discovery.package == "pkg", (
        f"a discovery must carry the root it describes: {discovery!r}"
    )
    assert [
        (item.module, item.source_path, item.is_package_init)
        for item in discovery.modules
    ] == [
        ("pkg", package_root / "__init__.py", True),
        ("pkg.domain", package_root / "domain" / "__init__.py", True),
        ("pkg.domain.model", package_root / "domain" / "model.py", False),
    ], f"discovery must pair each file with its module and kind: {discovery!r}"


def test_discover_modules_orders_by_source_path(tmp_path: Path) -> None:
    """Discovery order comes from sorting, not from filesystem iteration.

    The order is observable: a caller keying a mapping by module name keeps the
    first record it sees, so which package wins a duplicate name is decided
    here rather than by whichever directory the filesystem happens to list
    first.
    """
    package_root = tmp_path / "pkg"
    for relative_path in ("zebra.py", "alpha.py", "middle/__init__.py"):
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")

    discovery = discover_modules(package_root, "pkg")

    assert [item.module for item in discovery.modules] == [
        "pkg.alpha",
        "pkg.middle",
        "pkg.zebra",
    ], f"discovery must be sorted by source path: {discovery!r}"


def test_discover_modules_reports_a_directory_it_cannot_list(
    tmp_path: Path,
) -> None:
    """An unreadable subtree is an error, never a shorter module list.

    ``Path.rglob`` swallows ``OSError`` and returns what it managed to list, so
    an unreadable directory would look like an empty one and the run would
    report clean coverage of files the walk never saw. Discovery must surface
    the failure and name the directory instead.
    """
    package_root = tmp_path / "pkg"
    locked = package_root / "locked"
    locked.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (locked / "hidden.py").write_text("", encoding="utf-8")
    locked.chmod(0)
    try:
        with pytest.raises(DiscoveryError) as exc_info:
            discover_modules(package_root, "pkg")
    finally:
        # Restore search permission so pytest can clean the tree up.
        locked.chmod(0o755)

    assert "locked" in str(exc_info.value), (
        f"the error must name the directory to fix, got {exc_info.value!r}"
    )


def test_relative_import_base_from_module() -> None:
    """Relative imports from modules resolve against the containing package."""
    assert (
        relative_import_base("pkg.application.service", is_package_init=False, level=2)
        == "pkg"
    )


def test_collected_statements_follow_source_order(tmp_path: Path) -> None:
    """Statements come back in source order, even across a nested block.

    ``ast.walk`` yields breadth-first, so an import nested in a function body
    is visited after later top-level imports. Last-binding-wins analysis reads
    that sequence in order, so the collection must sort by source position
    rather than trust the walk.

    The fixture mixes direct and ``from`` imports so that the assertion holds
    across both statement kinds, and it reads ``line``, which every statement
    carries regardless of kind.
    """
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    source = package_root / "module.py"
    source.write_text(
        "import first\n\n\ndef helper():\n    from . import nested\n\n\nimport last\n",
        encoding="utf-8",
    )

    statements = collect_import_statements(source, module="pkg.module")

    assert [statement.line for statement in statements] == [1, 5, 8], (
        "collected statements must be sorted into source order"
    )
