"""pytest-bdd steps for end-to-end Hecate fixture checks."""

from __future__ import annotations

import dataclasses as dc
import typing as typ
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from hecate.cli import main

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

scenarios("../features/architecture_check.feature")


@dc.dataclass(slots=True)
class CliRun:
    """Captured CLI result for a behavioural scenario."""

    exit_code: int
    stdout: str
    stderr: str


@dc.dataclass(slots=True)
class FixtureContext:
    """Mutable fixture workspace shared across steps."""

    root: Path
    config: Path
    override_config: Path | None = None
    result: CliRun | None = None


@given(parsers.parse('the "{fixture}" fixture package'), target_fixture="fixture_ctx")
def given_fixture_package(tmp_path: Path, fixture: str) -> FixtureContext:
    """Create one named fixture package and its default Hecate config."""
    package_root = tmp_path / "sample"
    _write_base_package(package_root)
    _write_fixture(package_root, fixture)
    config = tmp_path / "pyproject.toml"
    config.write_text(_policy_toml(), encoding="utf-8")
    return FixtureContext(root=tmp_path, config=config)


@given("an override config that permits every fixture group")
def given_override_config(fixture_ctx: FixtureContext) -> None:
    """Create an explicit config that makes the package pass."""
    override_config = fixture_ctx.root / "override.toml"
    override_config.write_text(_policy_toml(allow_everything=True), encoding="utf-8")
    fixture_ctx.override_config = override_config


@given("an invalid Hecate config", target_fixture="fixture_ctx")
def given_invalid_config(tmp_path: Path) -> FixtureContext:
    """Create a config with an undeclared allowed group."""
    package_root = tmp_path / "sample"
    _write_base_package(package_root)
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = ["missing"]
""",
        encoding="utf-8",
    )
    return FixtureContext(root=tmp_path, config=config)


@when("I run Hecate against the fixture")
def when_run_hecate(fixture_ctx: FixtureContext, capsys: CaptureFixture[str]) -> None:
    """Run the checker with the fixture's explicit config."""
    exit_code = main(["check", "--config", str(fixture_ctx.config)])
    captured = capsys.readouterr()
    fixture_ctx.result = CliRun(exit_code, captured.out, captured.err)


@when("I run Hecate with default config discovery")
def when_run_hecate_default(
    fixture_ctx: FixtureContext,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Run the checker from the fixture root using pyproject discovery."""
    monkeypatch.chdir(fixture_ctx.root)
    exit_code = main(["check"])
    captured = capsys.readouterr()
    fixture_ctx.result = CliRun(exit_code, captured.out, captured.err)


@when("I run Hecate with the override config")
def when_run_hecate_override(
    fixture_ctx: FixtureContext, capsys: CaptureFixture[str]
) -> None:
    """Run the checker with an explicit override config."""
    assert fixture_ctx.override_config is not None, (
        f"expected override config path, got {fixture_ctx.override_config!r}"
    )
    exit_code = main(["check", "--config", str(fixture_ctx.override_config)])
    captured = capsys.readouterr()
    fixture_ctx.result = CliRun(exit_code, captured.out, captured.err)


@then(parsers.parse('the exit code is "{exit_code:d}"'))
def then_exit_code(fixture_ctx: FixtureContext, exit_code: int) -> None:
    """Assert the command returned the expected exit code."""
    result = _result(fixture_ctx)
    assert result.exit_code == exit_code, (
        f"expected exit code {exit_code}, got {result.exit_code}; "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


@then(parsers.parse('the diagnostics contain "{text}"'))
def then_diagnostics_contain(fixture_ctx: FixtureContext, text: str) -> None:
    """Assert stdout contains expected diagnostic text."""
    stdout = _result(fixture_ctx).stdout
    assert text in stdout, f"expected stdout to contain {text!r}, got {stdout!r}"


@then(parsers.parse('stderr contains "{text}"'))
def then_stderr_contains(fixture_ctx: FixtureContext, text: str) -> None:
    """Assert stderr contains expected diagnostic text."""
    stderr = _result(fixture_ctx).stderr
    assert text in stderr, f"expected stderr to contain {text!r}, got {stderr!r}"


def _result(fixture_ctx: FixtureContext) -> CliRun:
    assert fixture_ctx.result is not None, (
        f"expected CLI result to be recorded, got {fixture_ctx.result!r}"
    )
    return fixture_ctx.result


def _write_base_package(package_root: Path) -> None:
    """Write the shared sample package skeleton beneath ``package_root``."""
    for directory in (
        package_root,
        package_root / "domain",
        package_root / "application",
        package_root / "adapters",
        package_root / "adapters" / "outbound",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "config.py").write_text("", encoding="utf-8")
    (package_root / "cli.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "model.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "port.py").write_text("", encoding="utf-8")
    (package_root / "application" / "service.py").write_text("", encoding="utf-8")
    (package_root / "adapters" / "outbound" / "db.py").write_text("", encoding="utf-8")


def _write_fixture(package_root: Path, fixture: str) -> None:
    """Write one predefined fixture variant into the sample package root."""
    fixtures = {
        "clean_package": (
            "application/service.py",
            "from sample.domain import model\n",
        ),
        "domain_imports_adapter": (
            "domain/model.py",
            "from sample.adapters.outbound import db\n",
        ),
        "application_imports_adapter": (
            "application/service.py",
            "from sample.adapters.outbound import db\n",
        ),
        "application_imports_domain_port": (
            "application/service.py",
            "from sample.domain import port\n",
        ),
        "composition_root_wires_adapters": (
            "config.py",
            "from sample.adapters.outbound import db\n",
        ),
        "inbound_cli_imports_config": ("cli.py", "from sample import config\n"),
        "inbound_cli_imports_outbound_adapter": (
            "cli.py",
            "from sample.adapters.outbound import db\n",
        ),
        "domain_imports_external_infrastructure": (
            "domain/model.py",
            "import sqlalchemy\n",
        ),
    }
    if fixture == "application_imports_reexported_adapter":
        (package_root / "adapters" / "__init__.py").write_text(
            "from .outbound import db\n__all__ = ['db']\n",
            encoding="utf-8",
        )
        fixtures[fixture] = (
            "application/service.py",
            "from sample.adapters import db\n",
        )
    if fixture == "application_imports_star_reexported_adapter":
        (package_root / "adapters" / "__init__.py").write_text(
            "from .outbound import *\n",
            encoding="utf-8",
        )
        (package_root / "adapters" / "outbound" / "__init__.py").write_text(
            "from . import db\n__all__ = ['db']\n",
            encoding="utf-8",
        )
        fixtures[fixture] = (
            "application/service.py",
            "from sample.adapters import db\n",
        )
    assert fixture in fixtures, (
        f"Unknown fixture {fixture!r}, valid fixtures: {sorted(fixtures.keys())}"
    )
    relative_path, contents = fixtures[fixture]
    (package_root / relative_path).write_text(contents, encoding="utf-8")


def _policy_toml(*, allow_everything: bool = False) -> str:
    """Return the sample policy TOML, optionally allowing every group edge."""
    allowed = (
        '["composition_root", "domain", "application", "inbound_adapter", '
        '"outbound_adapter", "adapter", "infrastructure"]'
    )
    application_allowed = allowed if allow_everything else '["application", "domain"]'
    domain_allowed = allowed if allow_everything else '["domain"]'
    inbound_allowed = (
        allowed
        if allow_everything
        else '["inbound_adapter", "composition_root", "application", "domain"]'
    )
    return f"""
[tool.hecate]
root_packages = ["sample"]
include_external_packages = true
default_rule_id = "HEC001"

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.config"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = {domain_allowed}

[[tool.hecate.groups]]
name = "application"
prefixes = ["sample.application"]
allowed = {application_allowed}

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.cli", "sample.adapters.inbound"]
allowed = {inbound_allowed}

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = ["sample.adapters.outbound"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["sample.adapters"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "infrastructure"
prefixes = ["sqlalchemy"]
allowed = ["infrastructure"]
"""
