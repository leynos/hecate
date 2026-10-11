"""Tests for the unclassified-module configuration and CLI behaviour.

``unclassified_modules`` is read at startup and then decides both what a run
reports and which exit code it returns. These tests pin the configuration half
(the three documented modes, the default, and rejection of anything else) and
the command half (text and JSON output, the exit-code policy, and the byte
identical default output), because a mode that parsed but did not reach the
renderer would pass a config-only test.

The configuration half shares ``_assert_config_rejects`` with
``test_config_output_cli.py``; it is small enough that duplicating it here keeps
each module readable on its own.
"""

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
