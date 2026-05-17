"""Unit tests for config loading, output, and CLI exits."""

from __future__ import annotations

import typing as typ
from pathlib import Path

import pytest

from hecate.checker import ArchitectureCheckResult
from hecate.cli import main
from hecate.config import ConfigError, load_config
from hecate.diagnostics import ArchitectureViolation
from hecate.output import render_json, render_text

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def test_config_validation_rejects_unknown_allowed_group(tmp_path: Path) -> None:
    """Policy validation reports unknown group names."""
    config = tmp_path / "pyproject.toml"
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["missing"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as error:
        load_config(config)

    assert str(config) in str(error.value)
    assert "undeclared groups" in str(error.value)


def test_text_and_json_output_include_violation_identity(tmp_path: Path) -> None:
    """Diagnostic renderers preserve the same violation identity."""
    violation = ArchitectureViolation(
        rule_id="HEC001",
        importer="pkg.domain.model",
        imported="pkg.adapters.db",
        importer_group="domain",
        imported_group="adapter",
        source_path=tmp_path / "pkg/domain/model.py",
        line=1,
    )
    result = ArchitectureCheckResult(violations=(violation,))

    assert "pkg.domain.model:1" in render_text(result)
    assert '"imported": "pkg.adapters.db"' in render_json(result)


def test_cli_returns_two_for_invalid_config(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Invalid configuration exits with code 2."""
    config = tmp_path / "missing.toml"

    exit_code = main(["check", "--config", str(config)])

    assert exit_code == 2
    assert "configuration file does not exist" in capsys.readouterr().err


def test_cli_returns_two_for_unmatched_ignore(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Fail-on-unmatched-ignore exits with code 2."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]

[[tool.hecate.ignore_imports]]
importer = "pkg.missing"
imported = "pkg.other"
reason = "No longer used."
""",
        encoding="utf-8",
    )

    exit_code = main(["check", "--config", str(config), "--fail-on-unmatched-ignore"])

    assert exit_code == 2
    assert "unmatched ignore pkg.missing -> pkg.other" in capsys.readouterr().err
