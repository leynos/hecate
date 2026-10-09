"""Unit tests for AST import collection helpers."""

from __future__ import annotations

from pathlib import Path

from hecate.imports import (
    collect_import_statements,
    compute_module_name,
    relative_import_base,
)


def test_compute_module_name_handles_package_init() -> None:
    """Package ``__init__`` files map to the package module."""
    assert compute_module_name(Path("pkg"), "pkg", Path("pkg/__init__.py")) == "pkg"


def test_compute_module_name_handles_nested_module() -> None:
    """Nested source paths map to dotted module names."""
    module = compute_module_name(Path("pkg"), "pkg", Path("pkg/application/service.py"))
    assert module == "pkg.application.service"


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

    statements = collect_import_statements(source, root=package_root, package="pkg")

    assert [statement.line for statement in statements] == [1, 5, 8], (
        "collected statements must be sorted into source order"
    )
