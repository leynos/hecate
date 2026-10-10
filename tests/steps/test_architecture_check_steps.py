"""pytest-bdd steps for end-to-end Hecate fixture checks."""

from __future__ import annotations

import dataclasses as dc
import json
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


@when("I run Hecate against the fixture with JSON output")
def when_run_hecate_json(
    fixture_ctx: FixtureContext, capsys: CaptureFixture[str]
) -> None:
    """Run the checker with machine-readable output for coverage assertions."""
    _run_checker(fixture_ctx, capsys, "--format", "json")


@when("I run Hecate against the fixture in strict mode")
def when_run_hecate_strict(
    fixture_ctx: FixtureContext, capsys: CaptureFixture[str]
) -> None:
    """Run the checker in strict mode with coverage reporting enabled."""
    _run_checker(fixture_ctx, capsys, "--strict", "--show-coverage")


def _run_checker(
    fixture_ctx: FixtureContext,
    capsys: CaptureFixture[str],
    *extra_args: str,
) -> None:
    """Run the CLI against the fixture config and record the captured result.

    Every ``when`` step drives the same command and differs only in the flags,
    so the invocation and capture live here and each step names its flags.
    """
    exit_code = main(["check", "--config", str(fixture_ctx.config), *extra_args])
    captured = capsys.readouterr()
    fixture_ctx.result = CliRun(exit_code, captured.out, captured.err)


@then(parsers.parse('the coverage report contains "{text}"'))
def then_coverage_contains(fixture_ctx: FixtureContext, text: str) -> None:
    """Assert the JSON coverage report mentions an expected edge state."""
    payload = json.loads(_result(fixture_ctx).stdout)
    states = [entry["state"] for entry in payload["coverage"]]
    assert text in states, f"expected coverage state {text!r}, got {states!r}"


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


@then(parsers.parse('the diagnostics omit "{text}"'))
def then_diagnostics_omit(fixture_ctx: FixtureContext, text: str) -> None:
    """Assert stdout does not mention an origin that must not be expanded."""
    stdout = _result(fixture_ctx).stdout
    assert text not in stdout, f"expected stdout to omit {text!r}, got {stdout!r}"


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


@dc.dataclass(frozen=True, slots=True)
class FixtureVariant:
    """One named fixture: the edge to check plus any barrel files it needs.

    ``extra`` holds package-barrel sources written before the import site, so
    variants that exercise re-export semantics declare their barrels as data
    rather than as branching setup code.
    """

    target: str
    contents: str
    extra: tuple[tuple[str, str], ...] = ()


_EXPOSED_BARREL = (
    "adapters/__init__.py",
    "from .outbound import db\n__all__ = ['db']\n",
)

_HIDDEN_BARREL = (
    "adapters/__init__.py",
    "from .outbound import db\n__all__ = []\n",
)

_FIXTURE_VARIANTS: dict[str, FixtureVariant] = {
    "clean_package": FixtureVariant(
        "application/service.py", "from sample.domain import model\n"
    ),
    "domain_imports_adapter": FixtureVariant(
        "domain/model.py", "from sample.adapters.outbound import db\n"
    ),
    "application_imports_adapter": FixtureVariant(
        "application/service.py", "from sample.adapters.outbound import db\n"
    ),
    "application_imports_domain_port": FixtureVariant(
        "application/service.py", "from sample.domain import port\n"
    ),
    "composition_root_wires_adapters": FixtureVariant(
        "config.py", "from sample.adapters.outbound import db\n"
    ),
    "inbound_cli_imports_config": FixtureVariant(
        "cli.py", "from sample import config\n"
    ),
    "inbound_cli_imports_outbound_adapter": FixtureVariant(
        "cli.py", "from sample.adapters.outbound import db\n"
    ),
    "domain_imports_external_infrastructure": FixtureVariant(
        "domain/model.py", "import sqlalchemy\n"
    ),
    # A barrel advertising a re-export to wildcards and to explicit imports.
    "application_imports_reexported_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(_EXPOSED_BARREL,),
    ),
    # A barrel that reaches its re-export through a star import.
    "application_imports_star_reexported_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(
            ("adapters/__init__.py", "from .outbound import *\n"),
            ("adapters/outbound/__init__.py", "from . import db\n__all__ = ['db']\n"),
        ),
    ),
    # __all__ hides db from wildcards but cannot unbind it, so this explicit
    # re-export must still resolve to the outbound adapter.
    "application_imports_all_hidden_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(_HIDDEN_BARREL,),
    ),
    # A wildcard consumer, which must expand to the origin of db.
    "application_imports_wildcard_consumer": FixtureVariant(
        "application/service.py",
        "from sample.adapters import *\n",
        extra=(_EXPOSED_BARREL,),
    ),
    # A wildcard over __all__ = [] binds nothing beyond the module edge.
    "application_imports_empty_all_wildcard": FixtureVariant(
        "application/service.py",
        "from sample.adapters import *\n",
        extra=(_HIDDEN_BARREL,),
    ),
    # A relative import through a package barrel must resolve like the absolute
    # form; both spell the same edge.
    "application_imports_relative_barrel_adapter": FixtureVariant(
        "application/service.py",
        "from sample.application import db\n",
        extra=(
            ("application/__init__.py", "from ..adapters import db\n"),
            _EXPOSED_BARREL,
        ),
    ),
    # The new subtree matches no configured group, so a non-strict run passes
    # while still reporting the edge as unclassified.
    "application_imports_unclassified_subtree": FixtureVariant(
        "application/service.py",
        "from sample.newthing import helper\n",
        extra=(
            ("newthing/__init__.py", ""),
            ("newthing/helper.py", ""),
        ),
    ),
    # The symbol does not exist, so the internal edge is unresolved.
    "application_imports_unresolved_symbol": FixtureVariant(
        "application/service.py", "from sample.domain import missing_symbol\n"
    ),
}


def _write_fixture(package_root: Path, fixture: str) -> None:
    """Write one predefined fixture variant into the sample package root."""
    assert fixture in _FIXTURE_VARIANTS, (
        f"Unknown fixture {fixture!r}, valid fixtures: {sorted(_FIXTURE_VARIANTS)}"
    )
    variant = _FIXTURE_VARIANTS[fixture]
    for relative_path, contents in variant.extra:
        path = package_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    (package_root / variant.target).write_text(variant.contents, encoding="utf-8")


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
