"""Unit tests for config loading and CLI exits."""

from __future__ import annotations

import json
import typing as typ
from pathlib import Path

import pytest

from hecate.cli import main
from hecate.config import ConfigError, load_config
from hecate.policy import Severity

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


def test_config_rejects_unknown_unresolved_severity(tmp_path: Path) -> None:
    """An unknown severity name is a configuration error."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]
unresolved_internal_severity = "loud"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        "unresolved_internal_severity",
    )


_UNCLASSIFIED_MODULES_CONFIG = """
[tool.hecate]
root_packages = ["pkg"]
{mode}

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
"""


def _write_unclassified_modules_config(tmp_path: Path, mode_setting: str) -> Path:
    """Write a minimal config carrying the given mode setting verbatim."""
    (tmp_path / "pkg").mkdir(exist_ok=True)
    config = tmp_path / "pyproject.toml"
    config.write_text(
        _UNCLASSIFIED_MODULES_CONFIG.format(mode=mode_setting), encoding="utf-8"
    )
    return config


@pytest.mark.parametrize(
    "mode", ["ignore", "warn", "error"], ids=["ignore", "warn", "error"]
)
def test_config_accepts_each_unclassified_modules_mode(
    tmp_path: Path, mode: str
) -> None:
    """Every documented mode round-trips from TOML into the policy."""
    config = _write_unclassified_modules_config(
        tmp_path, f'unclassified_modules = "{mode}"'
    )

    hecate_config = load_config(config)

    assert hecate_config.policy.unclassified_modules == mode, (
        f"expected the configured mode {mode!r}, got {hecate_config.policy!r}"
    )


def test_config_defaults_unclassified_modules_to_ignore(tmp_path: Path) -> None:
    """Omitting the key keeps the historical behaviour.

    The default is the whole backwards-compatibility contract for this option,
    so it is asserted on its own rather than inferred from a mode test.
    """
    config = _write_unclassified_modules_config(tmp_path, "")

    hecate_config = load_config(config)

    assert hecate_config.policy.unclassified_modules == "ignore", (
        f"expected the documented default, got {hecate_config.policy!r}"
    )


@pytest.mark.parametrize(
    "mode_setting",
    ['unclassified_modules = "loud"', "unclassified_modules = 7"],
    ids=["unsupported-value", "non-string-value"],
)
def test_config_rejects_invalid_unclassified_modules(
    tmp_path: Path, mode_setting: str
) -> None:
    """An unsupported or non-string mode is a configuration error.

    Both cases must name the permitted values, because the setting is a closed
    set and a reader needs the alternatives, not just the rejection.
    """
    _assert_config_rejects(
        tmp_path,
        _UNCLASSIFIED_MODULES_CONFIG.format(mode=mode_setting),
        "tool.hecate.unclassified_modules",
        '"ignore"',
        '"warn"',
        '"error"',
    )


def test_config_loads_strict_and_severity_options(tmp_path: Path) -> None:
    """Strict mode and the unresolved severity are read from TOML."""
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]
strict = true
unresolved_internal_severity = "warning"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    hecate_config = load_config(config)

    assert hecate_config.policy.strict is True, (
        f"expected strict mode from TOML, got {hecate_config.policy!r}"
    )
    assert hecate_config.policy.unresolved_internal_severity is Severity.WARNING, (
        f"expected the configured severity, got {hecate_config.policy!r}"
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


_UNCLASSIFIED_PACKAGE = """
[tool.hecate]
root_packages = ["pkg"]
unclassified_modules = "{mode}"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
"""


def _write_unclassified_package(tmp_path: Path, mode: str) -> Path:
    """Create a package with a subtree no configured group claims."""
    package_root = tmp_path / "pkg"
    (package_root / "domain").mkdir(parents=True)
    (package_root / "newfeature").mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "newfeature" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "newfeature" / "helper.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(_UNCLASSIFIED_PACKAGE.format(mode=mode), encoding="utf-8")
    return config


def test_cli_warn_mode_reports_without_failing(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """``warn`` names the unclassified modules and still exits 0.

    A warning that changed the exit code would be an error under another name,
    and a warning hidden behind a flag would make the setting pointless, so
    both halves are asserted together.
    """
    config = _write_unclassified_package(tmp_path, "warn")

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 0, f"warn mode must not change the exit code, got {output!r}"
    assert "HEC002 warning pkg.newfeature" in output, (
        f"the warning must name the unclassified module, got {output!r}"
    )
    assert "no architecture group matched this module" in output, (
        f"the warning must explain the finding, got {output!r}"
    )
    assert "hecate: architecture check passed" in output, (
        f"a warning-only run must still report success, got {output!r}"
    )


def test_cli_error_mode_fails_the_check(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """``error`` exits 1 and prints the finding without a pass line."""
    config = _write_unclassified_package(tmp_path, "error")

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 1, f"error mode must fail the check, got {output!r}"
    assert "HEC002 error pkg.newfeature" in output, (
        f"the failure must name the unclassified module, got {output!r}"
    )
    assert "architecture check passed" not in output, (
        f"a failing run must not claim success, got {output!r}"
    )


def test_cli_ignore_mode_stays_silent(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The default mode keeps the output byte-identical to the old shape."""
    config = _write_unclassified_package(tmp_path, "ignore")

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 0, f"the default must pass, got {output!r}"
    assert output == "hecate: architecture check passed\n", (
        f"the default output must be unchanged, got {output!r}"
    )


def test_cli_error_mode_json_lists_unclassified_modules(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """JSON carries a sorted ``unclassified_modules`` array with ``ok`` false."""
    config = _write_unclassified_package(tmp_path, "error")

    exit_code = main(["check", "--config", str(config), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1, f"error mode must fail the check, got {payload!r}"
    assert payload["ok"] is False, f"error findings must clear ok, got {payload!r}"
    modules = [entry["module"] for entry in payload["unclassified_modules"]]
    assert modules == ["pkg", "pkg.newfeature", "pkg.newfeature.helper"], (
        f"expected a sorted module list, got {modules!r}"
    )
    entry = payload["unclassified_modules"][0]
    assert entry["rule_id"] == "HEC002", f"expected the module rule id, got {entry!r}"
    assert entry["severity"] == "error", f"expected error severity, got {entry!r}"
    assert entry["message"] == "no architecture group matched this module", (
        f"expected the coverage message, got {entry!r}"
    )
    assert entry["source_path"].endswith("pkg/__init__.py"), (
        f"expected the first source path to win, got {entry!r}"
    )


def test_cli_warn_mode_json_reports_an_empty_array_when_fully_classified(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A reporting mode carries the section even when it is empty.

    An absent key reads as "not reported" while an empty array reads as
    "evaluated and clean", and a consumer needs to tell those apart. The tree
    here is classified end to end, including its initializers, so the run has
    nothing to report but still has to say so.
    """
    package_root = tmp_path / "pkg"
    (package_root / "domain").mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]
unclassified_modules = "warn"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    exit_code = main(["check", "--config", str(config), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, f"a classified tree must pass, got {payload!r}"
    assert "unclassified_modules" in payload, (
        f"a reporting mode must carry the section, got {payload!r}"
    )
    assert payload["unclassified_modules"] == [], (
        f"a fully classified tree must report an empty list, got {payload!r}"
    )


def test_cli_default_json_omits_unclassified_modules(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The default payload gains no key, so existing consumers are unaffected."""
    config = _write_unclassified_package(tmp_path, "ignore")

    exit_code = main(["check", "--config", str(config), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, f"the default must pass, got {payload!r}"
    assert "unclassified_modules" not in payload, (
        f"ignore mode must not add the section, got {sorted(payload)}"
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
