"""Coverage for the CLI's configured and overridden source roots."""

from __future__ import annotations

import typing as typ
from pathlib import Path

import pytest

from hecate.cli import main

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def _write_forbidden_adapter_import(root: Path, package_name: str) -> None:
    """Create a domain module importing a separately classified adapter."""
    adapters_root = root / "adapters"
    adapters_root.mkdir(parents=True)
    (root / "domain.py").write_text(
        f"import {package_name}.adapters.storage\n",
        encoding="utf-8",
    )
    (adapters_root / "storage.py").write_text("", encoding="utf-8")


def test_cli_scans_a_package_table_source_root(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Explicit public names map to and scan their configured source root."""
    source_root = tmp_path / "src" / "internal_name"
    source_root.mkdir(parents=True)
    _write_forbidden_adapter_import(source_root, "public_name")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]

[[tool.hecate.package]]
name = "public_name"
root = "src/internal_name"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["public_name.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["public_name.adapters"]
allowed = ["adapter"]
""",
        encoding="utf-8",
    )

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 1, (
        "a forbidden import in the configured package source root must fail the check"
    )
    assert "public_name.domain:1" in output, (
        f"the violation must use the configured public package name: {output!r}"
    )
    assert "public_name.adapters.storage" in output, (
        f"the violation must identify the imported adapter module: {output!r}"
    )


def test_cli_package_and_root_overrides_replace_configured_roots(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Paired CLI overrides scan the requested package instead of config roots."""
    source_root = tmp_path / "selected"
    source_root.mkdir()
    _write_forbidden_adapter_import(source_root, "selected")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["configured_but_missing"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["selected.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["selected.adapters"]
allowed = ["adapter"]
""",
        encoding="utf-8",
    )

    exit_code = main([
        "check",
        "--config",
        str(config),
        "--package",
        "selected",
        "--root",
        str(source_root),
    ])

    output = capsys.readouterr().out
    assert exit_code == 1, (
        "paired CLI source overrides must scan the selected package root"
    )
    assert "selected.domain:1" in output, (
        f"the CLI override must identify the selected package: {output!r}"
    )


@pytest.mark.parametrize(
    ("override_args", "case_id"),
    [
        (("--package", "selected"), "missing-root"),
        (("--root", "selected"), "missing-package"),
    ],
    ids=("missing-root", "missing-package"),
)
def test_cli_requires_package_and_root_overrides_together(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    override_args: tuple[str, str],
    case_id: str,
) -> None:
    """An ad hoc package selection rejects either unpaired option."""
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "pkg"
prefixes = ["pkg"]
allowed = ["pkg"]
""",
        encoding="utf-8",
    )

    exit_code = main(["check", "--config", str(config), *override_args])

    stderr = capsys.readouterr().err
    assert exit_code == 2, (
        f"{case_id}: an unpaired package/root override must be a configuration error"
    )
    assert "--package and --root must be provided together" in stderr, (
        f"{case_id}: the CLI must explain the required override pair: {stderr!r}"
    )
