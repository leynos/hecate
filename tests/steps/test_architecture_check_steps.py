"""pytest-bdd steps for end-to-end Hecate fixture checks."""

from __future__ import annotations

import dataclasses as dc
import json
import typing as typ
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from hecate.cli import main

from .fixture_setup import policy_toml, write_base_package, write_fixture
from .shadowed_prefix_fixtures import write_composition_root_config

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
    write_base_package(package_root)
    write_fixture(package_root, fixture)
    config = tmp_path / "pyproject.toml"
    config.write_text(policy_toml(), encoding="utf-8")
    return FixtureContext(root=tmp_path, config=config)


@given("an override config that permits every fixture group")
def given_override_config(fixture_ctx: FixtureContext) -> None:
    """Create an explicit config that makes the package pass."""
    override_config = fixture_ctx.root / "override.toml"
    override_config.write_text(policy_toml(allow_everything=True), encoding="utf-8")
    fixture_ctx.override_config = override_config


@given(
    parsers.parse('a Hecate config with unclassified modules set to "{mode}"'),
)
def given_unclassified_modules_config(fixture_ctx: FixtureContext, mode: str) -> None:
    """Rewrite the fixture config to report modules no group claims."""
    fixture_ctx.config.write_text(
        policy_toml(unclassified_modules=mode), encoding="utf-8"
    )


@given("an invalid Hecate config", target_fixture="fixture_ctx")
def given_invalid_config(tmp_path: Path) -> FixtureContext:
    """Create a config with an undeclared allowed group."""
    package_root = tmp_path / "sample"
    write_base_package(package_root)
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


@given(
    parsers.parse('a "{order}" composition-root exception fixture'),
    target_fixture="fixture_ctx",
)
def given_composition_root_fixture(tmp_path: Path, order: str) -> FixtureContext:
    """Create a broad-first or narrow-first composition-root policy."""
    assert order in {"broad-first", "narrow-first"}, f"unknown order {order!r}"
    config = write_composition_root_config(
        tmp_path, narrow_first=order == "narrow-first"
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
