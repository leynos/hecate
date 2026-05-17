"""Unit tests for checker orchestration rules."""

from __future__ import annotations

from pathlib import Path

from hecate.checker import check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import ArchitecturePolicy, ModuleGroup


def test_external_imports_are_skipped_when_disabled(tmp_path: Path) -> None:
    """External classified prefixes require explicit opt-in."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain.py").write_text("import sqlalchemy\n", encoding="utf-8")
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=ArchitecturePolicy(
            groups=(
                ModuleGroup("domain", ("pkg",), ("domain",)),
                ModuleGroup("infrastructure", ("sqlalchemy",), ("infrastructure",)),
            ),
            include_external_packages=False,
        ),
    )

    result = check_architecture(config)

    assert result.ok, f"expected external import to be skipped, got {result!r}"
