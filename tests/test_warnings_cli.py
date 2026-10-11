"""CLI and configuration tests for warning-level dependency directions.

Warnings are a policy declaration, so most of what can go wrong is a
configuration mistake: a target no group declares, a target that is also
allowed, or a malformed list. The rest is exit-status behaviour, which has to
keep the warning visible in the output of the run it fails.
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


def test_config_validation_rejects_unknown_warn_group(tmp_path: Path) -> None:
    """Policy validation reports undeclared warning targets.

    A warning target that no group declares can never be reached, so it would
    silently tolerate nothing. Rejecting it keeps the migration list honest.
    """
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
warn = ["legacy"]
""",
        "undeclared groups",
        "legacy",
    )


def test_config_validation_rejects_allowed_and_warn_overlap(tmp_path: Path) -> None:
    """A target cannot be both allowed and warned.

    Allowed means silent and warned means reported; accepting both would make
    the outcome depend on which check ran first rather than on the config.
    """
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain", "application"]
warn = ["application"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["pkg.application"]
allowed = ["application"]
""",
        "group domain",
        "both allowed and warn",
        "application",
    )


def test_config_validation_rejects_non_list_warn(tmp_path: Path) -> None:
    """A ``warn`` value that is not a string list is a configuration error."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
warn = "legacy"
""",
        "must be a string list",
    )


def test_config_validation_rejects_blank_warn_entry(tmp_path: Path) -> None:
    """A blank warning target cannot match a group and is rejected."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
warn = ["  "]
""",
        "must be a string list",
    )


def test_config_accepts_absent_and_empty_warn_lists(tmp_path: Path) -> None:
    """An omitted ``warn`` key and an explicit empty list both mean no warnings.

    Existing configurations predate the key, so omitting it has to keep
    working; an empty list is how a migration records that it has finished.
    """
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "legacy"
prefixes = ["pkg.legacy"]
allowed = ["legacy"]
warn = []
""",
        encoding="utf-8",
    )

    hecate_config = load_config(config)

    warn_lists = {group.name: group.warn for group in hecate_config.policy.groups}
    assert warn_lists == {"domain": (), "legacy": ()}, (
        f"expected empty warning lists, got {warn_lists!r}"
    )


@pytest.fixture
def warned_edge_config(tmp_path: Path) -> Path:
    """Create a package with one edge tolerated at warning level.

    ``application`` warns ``adapter``, so the single import in the package is
    classified, reported, and passes on its own. The policy is what the CLI
    warning tests exercise; nothing else about the package is interesting.
    """
    package_root = tmp_path / "pkg"
    (package_root / "application").mkdir(parents=True)
    (package_root / "adapters").mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "application" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "application" / "service.py").write_text(
        "from pkg.adapters import database\n", encoding="utf-8"
    )
    (package_root / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "adapters" / "database.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["pkg.application"]
allowed = ["application"]
warn = ["adapter"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["pkg.adapters"]
allowed = ["adapter"]
""",
        encoding="utf-8",
    )
    return config


def test_cli_passes_with_warnings_by_default(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """A warned edge exits 0 and still reports itself.

    The whole point of the severity is that the migration can land without a
    red build, so exit code 0 and a visible diagnostic have to hold together.
    """
    exit_code = main(["check", "--config", str(warned_edge_config)])

    output = capsys.readouterr().out
    assert exit_code == 0, f"a warning must not fail by default, got {exit_code}"
    assert "(warning):" in output, f"expected the warned edge in stdout, got {output!r}"


def test_cli_fail_on_warnings_fails_a_warning_only_run(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """``--fail-on-warnings`` turns a warning-only run into exit code 1.

    The output is emitted before the exit code is decided, so a run that fails
    on warnings still shows which edges caused it.
    """
    exit_code = main([
        "check",
        "--config",
        str(warned_edge_config),
        "--fail-on-warnings",
    ])

    output = capsys.readouterr().out
    assert exit_code == 1, f"expected the flag to fail the run, got {exit_code}"
    assert "(warning):" in output, (
        f"expected the warned edge to survive into the failing run, got {output!r}"
    )


def test_cli_json_reports_warning_severity_and_ok(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """JSON carries the warning with its severity while ``ok`` stays true."""
    exit_code = main([
        "check",
        "--config",
        str(warned_edge_config),
        "--format",
        "json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, f"expected exit code 0, got {exit_code}"
    assert payload["ok"] is True, f"a warning must not clear ok, got {payload!r}"
    assert payload["violations"] == [], (
        f"a warned edge must not appear as a violation, got {payload!r}"
    )
    warnings = payload["warnings"]
    # ``from pkg.adapters import database`` reaches both the module and the
    # symbol through it, and both edges are warned.
    assert [entry["imported"] for entry in warnings] == [
        "pkg.adapters",
        "pkg.adapters.database",
    ], f"expected both expanded edges as warnings, got {warnings!r}"
    assert all(entry["severity"] == "warning" for entry in warnings), (
        f"expected warning severity on every entry, got {warnings!r}"
    )


def test_cli_json_reports_empty_warnings_for_unconfigured_policy(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A policy without warning targets reports an empty warnings list."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
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

    exit_code = main(["check", "--config", str(config), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, f"expected exit code 0, got {exit_code}"
    assert payload["warnings"] == [], (
        f"expected an empty warnings list, got {payload!r}"
    )


def test_cli_warnings_and_violations_fail_the_run(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A violated edge still fails the run when warnings are also present."""
    package_root = tmp_path / "pkg"
    (package_root / "domain").mkdir(parents=True)
    (package_root / "application").mkdir()
    (package_root / "adapters").mkdir()
    for part in ("", "domain", "application", "adapters"):
        (package_root / part / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "model.py").write_text(
        "from pkg.adapters import database\n", encoding="utf-8"
    )
    (package_root / "application" / "service.py").write_text(
        "from pkg.adapters import database\n", encoding="utf-8"
    )
    (package_root / "adapters" / "database.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["pkg.application"]
allowed = ["application"]
warn = ["adapter"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["pkg.adapters"]
allowed = ["adapter"]
""",
        encoding="utf-8",
    )

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 1, f"a violation must fail the run, got {exit_code}"
    assert "pkg.domain.model:1 imports forbidden" in output, (
        f"expected the violation in stdout, got {output!r}"
    )
    assert "(warning):" in output, (
        f"expected the warning beside the violation, got {output!r}"
    )
