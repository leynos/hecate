"""Unit tests for AST import collection helpers."""

from __future__ import annotations

from pathlib import Path

from hecate.imports import collect_imports, compute_module_name, relative_import_base


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


def test_collect_imports_reads_direct_and_from_imports(tmp_path: Path) -> None:
    """Direct imports and ``from`` imports are both collected."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    source = package_root / "module.py"
    source.write_text(
        "import pkg.domain.model\nfrom .adapters import outbound\n",
        encoding="utf-8",
    )

    imports = collect_imports(source, root=package_root, package="pkg")

    assert [(item.importer, item.imported) for item in imports] == [
        ("pkg.module", "pkg.domain.model"),
        ("pkg.module", "pkg.adapters"),
        ("pkg.module", "pkg.adapters.outbound"),
    ]
