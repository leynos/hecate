"""Unit tests for config loading and CLI exits."""

from __future__ import annotations

import json
import typing as typ
from pathlib import Path

import pytest

from hecate.cli import main
from hecate.config import ConfigError, load_config

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


def test_config_validation_rejects_shadowed_narrower_prefix(
    tmp_path: Path,
) -> None:
    """A later exception cannot silently lose to an earlier broad group."""
    (tmp_path / "sample").mkdir()
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "inbound_adapter"]
""",
        "inbound_adapter",
        "sample.api",
        "composition_root",
        "sample.api.runtime",
        "place group 'composition_root' before group 'inbound_adapter'",
        "narrower classification effective",
    )


def test_equal_group_prefix_diagnostic_recommends_removal(
    tmp_path: Path,
) -> None:
    """Equal prefixes need removal because ordering only swaps the winner."""
    (tmp_path / "sample").mkdir()
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api"]
allowed = ["composition_root"]
""",
        "remove the duplicate prefix from group 'composition_root'",
    )


def test_cli_strict_flag_overrides_configuration(tmp_path: Path) -> None:
    """``--strict`` on the command line overrides a non-strict config.

    The policy here classifies only ``pkg.domain``, so the consumer matches no
    group. ``domain/model.py`` exists, so the target resolves: the edge fails
    strictly because the consumer is unclassified, not because the import is
    unresolved. A non-strict run passes with a warning, and ``--strict``
    promotes that warning to a failure.
    """
    package_root = tmp_path / "pkg"
    (package_root / "domain").mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "model.py").write_text("", encoding="utf-8")
    (package_root / "consumer.py").write_text(
        "from pkg.domain import model\n", encoding="utf-8"
    )
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    lenient_exit = main(["check", "--config", str(config)])
    strict_exit = main(["check", "--config", str(config), "--strict"])

    assert lenient_exit == 0, (
        f"an unclassified edge must not fail a non-strict run, got {lenient_exit}"
    )
    assert strict_exit == 1, (
        f"expected --strict to override the config and fail, got {strict_exit}"
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
