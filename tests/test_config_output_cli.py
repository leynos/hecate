"""Unit tests for config loading, output, and CLI exits."""

from __future__ import annotations

import json
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


def _assert_config_rejects(
    tmp_path: Path,
    toml_text: str,
    *expected_substrings: str,
) -> None:
    """Scaffold a temp config and assert ``load_config`` raises ``ConfigError``.

    The config file path and every string in *expected_substrings* must appear in
    the resulting error message.
    """
    config = tmp_path / "pyproject.toml"
    (tmp_path / "pkg").mkdir(exist_ok=True)
    config.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    error_text = str(exc_info.value)
    assert str(config) in error_text, (
        f"expected config path {config!r} in error message: {error_text}"
    )
    for expected in expected_substrings:
        assert expected in error_text, (
            f"expected {expected!r} in error message: {error_text}"
        )


def test_config_validation_rejects_unknown_allowed_group(tmp_path: Path) -> None:
    """Policy validation reports unknown group names."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["missing"]
""",
        "undeclared groups",
    )


def test_config_validation_rejects_malformed_ignore_import(
    tmp_path: Path,
) -> None:
    """Policy validation rejects malformed ignore dotted strings."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]

[[tool.hecate.ignore_imports]]
importer = "pkg..domain"
imported = "pkg.other"
reason = "Malformed entry should fail."
""",
        "ignore_imports entry",
        "pkg..domain",
    )


def test_config_validation_rejects_invalid_dotted_identifier_segment(
    tmp_path: Path,
) -> None:
    """Policy validation rejects dotted strings with invalid identifiers."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.adapters-db"]
allowed = ["domain"]
""",
        "group domain",
        "pkg.adapters-db",
    )


def test_config_discovery_skips_pyproject_without_hecate_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config discovery continues past pyproject files without Hecate config."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    child_root = tmp_path / "child"
    child_root.mkdir()
    (child_root / "pyproject.toml").write_text(
        """
[project]
name = "not-hecate"
""",
        encoding="utf-8",
    )
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(child_root)

    hecate_config = load_config()

    assert hecate_config.source_path == config, (
        f"expected discovery to skip child pyproject, got {hecate_config.source_path}"
    )


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

    text_output = render_text(result)
    json_output = json.loads(render_json(result))

    assert "pkg.domain.model:1" in text_output, (
        f"expected text output to include violation location, got {text_output!r}"
    )
    assert json_output["violations"][0]["rule_id"] == "HEC001", (
        f"expected JSON rule_id HEC001, got {json_output!r}"
    )
    assert json_output["violations"][0]["importer"] == "pkg.domain.model", (
        f"expected JSON importer pkg.domain.model, got {json_output!r}"
    )
    assert json_output["violations"][0]["imported"] == "pkg.adapters.db", (
        f"expected JSON imported pkg.adapters.db, got {json_output!r}"
    )
    assert json_output["violations"][0]["line"] == 1, (
        f"expected JSON line 1, got {json_output!r}"
    )


def test_cli_returns_two_for_invalid_config(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Invalid configuration exits with code 2."""
    config = tmp_path / "missing.toml"

    exit_code = main(["check", "--config", str(config)])

    stderr = capsys.readouterr().err
    assert exit_code == 2, f"expected exit code 2, got {exit_code}"
    assert "configuration file does not exist" in stderr, (
        f"expected missing-file diagnostic in stderr, got {stderr!r}"
    )


def test_cli_output_format_option_keeps_format_flag(
    stale_ignore_config: Path, capsys: CaptureFixture[str]
) -> None:
    """The JSON output option remains exposed as ``--format``."""
    exit_code = main([
        "check",
        "--config",
        str(stale_ignore_config),
        "--format",
        "json",
    ])

    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert exit_code == 0, f"expected exit code 0, got {exit_code}"
    assert payload["ok"] is True, f"expected JSON success payload, got {payload!r}"


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

    stderr = capsys.readouterr().err
    assert exit_code == 2, f"expected exit code 2, got {exit_code}"
    assert "unmatched ignore pkg.missing -> pkg.other" in stderr, (
        f"expected unmatched-ignore diagnostic in stderr, got {stderr!r}"
    )


@pytest.fixture
def stale_ignore_config(tmp_path: Path) -> Path:
    """Create a package where an ignore covers an allowed import edge."""
    package_root = tmp_path / "pkg"
    adapters_root = package_root / "adapters"
    adapters_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain.py").write_text(
        "import pkg.adapters.db\n",
        encoding="utf-8",
    )
    (adapters_root / "__init__.py").write_text("", encoding="utf-8")
    (adapters_root / "db.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain", "adapter"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["pkg.adapters"]
allowed = ["adapter", "domain"]

[[tool.hecate.ignore_imports]]
importer = "pkg.domain"
imported = "pkg.adapters"
reason = "Previously forbidden."
""",
        encoding="utf-8",
    )
    return config


def test_allowed_import_does_not_match_stale_ignore(
    stale_ignore_config: Path, capsys: CaptureFixture[str]
) -> None:
    """Fail-on-unmatched-ignore reports ignores that suppress no violation."""
    exit_code = main([
        "check",
        "--config",
        str(stale_ignore_config),
        "--fail-on-unmatched-ignore",
    ])

    stderr = capsys.readouterr().err
    assert exit_code == 2, f"expected exit code 2, got {exit_code}"
    assert "unmatched ignore pkg.domain -> pkg.adapters" in stderr, (
        f"expected stale-ignore diagnostic in stderr, got {stderr!r}"
    )


def test_show_ignored_omits_allowed_import_with_stale_ignore(
    stale_ignore_config: Path, capsys: CaptureFixture[str]
) -> None:
    """Show-ignored only reports imports that were real suppressions."""
    exit_code = main(["check", "--config", str(stale_ignore_config), "--show-ignored"])

    output = capsys.readouterr().out
    assert exit_code == 0, f"expected exit code 0, got {exit_code}"
    assert "hecate: architecture check passed" in output, (
        f"expected pass diagnostic in stdout, got {output!r}"
    )
    assert "ignored:" not in output, (
        f"expected no ignored diagnostics for allowed import, got {output!r}"
    )
