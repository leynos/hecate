"""Fixture construction for shadowed-prefix BDD scenarios."""

import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path


def write_composition_root_config(root: Path, *, narrow_first: bool) -> Path:
    """Write a package where only the composition root may import domain."""
    package_root = root / "sample"
    for subpackage in ("", "api", "domain"):
        directory = package_root / subpackage
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "api" / "runtime.py").write_text(
        "from sample.domain import model\n",
        encoding="utf-8",
    )

    composition_root = """
[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "domain"]
"""
    inbound_adapter = """
[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter"]
"""
    domain = """
[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = ["domain"]
"""
    groups = (
        (composition_root, inbound_adapter, domain)
        if narrow_first
        else (inbound_adapter, composition_root, domain)
    )
    config = root / "pyproject.toml"
    config.write_text(
        '[tool.hecate]\nroot_packages = ["sample"]\n' + "".join(groups),
        encoding="utf-8",
    )
    return config
