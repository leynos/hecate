"""Makefile and CI contracts for the Skylos dead-code gate."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess  # noqa: S404 - contract tests invoke fixed local tools.
import tomllib
import typing as typ
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_MAKEUTIL_REVISION: typ.Final = "29fc5a1634ffbaa18a773eed9dff1b2838a45d9c"
_MAKEUTIL_TOOLCHAIN: typ.Final = "nightly-2026-05-28"
_MAKEUTIL_INSTALL_TOKENS: typ.Final = (
    "rustup",
    "toolchain",
    "install",
    "${MAKEUTIL_TOOLCHAIN}",
    "--profile",
    "minimal",
    "RUSTFLAGS=-Zpolonius=next",
    "cargo",
    "+${MAKEUTIL_TOOLCHAIN}",
    "install",
    "--git",
    "https://github.com/leynos/makeutil",
    "--rev",
    "${MAKEUTIL_REVISION}",
    "--locked",
    "--force",
    "makeutil",
)
_RUNTIME_METHOD_ENTRY_POINTS: typ.Final = frozenset({
    "hecate.diagnostics.IgnoredImportDiagnostic.render",
    "hecate.diagnostics.IgnoredImportDiagnostic.to_dict",
    "hecate.reexports.ReexportIndex.expand_import",
})


def _mapping(value: object, *, subject: str) -> dict[str, object]:
    """Return a JSON object, identifying the unexpected `subject` on failure."""
    assert isinstance(value, dict), f"expected {subject} to be a JSON object"
    return typ.cast("dict[str, object]", value)


def _objects(value: object, *, subject: str) -> list[dict[str, object]]:
    """Return a JSON object array, identifying the unexpected `subject`."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    return [_mapping(item, subject=f"{subject} item") for item in value]


def _text_sequence(value: object, *, subject: str) -> tuple[str, ...]:
    """Return a JSON string array, identifying the unexpected `subject`."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    assert all(isinstance(item, str) for item in value), (
        f"expected {subject} to contain only JSON strings"
    )
    return tuple(typ.cast("list[str]", value))


def _executable_path(name: str) -> str:
    """Resolve a fixed executable required by this contract suite."""
    executable = shutil.which(name)
    assert executable is not None, f"{name} must be available for Skylos contracts"
    return executable


def _makefile_report() -> dict[str, object]:
    """Return Makeutil's complete, successfully parsed Makefile report."""
    completed = subprocess.run(  # noqa: S603 - fixed parser command.
        (_executable_path("makeutil"), "parse", "Makefile"),
        capture_output=True,
        check=True,
        cwd=REPOSITORY_ROOT,
        text=True,
    )
    report = typ.cast("dict[str, object]", json.loads(completed.stdout))
    parse = _mapping(report.get("parse"), subject="Makeutil parse report")
    assert parse.get("status") == "complete", (
        f"makeutil did not complete the Makefile parse: {parse!r}"
    )
    return report


def _sole_variable(name: str) -> dict[str, object]:
    """Return Makeutil's sole variable fact for `name`."""
    variables = _objects(_makefile_report().get("variables"), subject="variables")
    matches = [variable for variable in variables if variable.get("name") == name]
    assert len(matches) == 1, (
        f"expected one Makefile variable named {name!r}, found {len(matches)}"
    )
    return matches[0]


def _sole_recipe_rule(target: str) -> dict[str, object]:
    """Return the sole parsed `target` rule containing recipes."""
    rules = _objects(_makefile_report().get("rules"), subject="rules")
    matches = [
        rule
        for rule in rules
        if target in _text_sequence(rule.get("targets"), subject="rule targets")
        and _objects(rule.get("recipes"), subject="rule recipes")
    ]
    assert len(matches) == 1, (
        f"expected one recipe-bearing Makefile rule named {target!r}, found "
        f"{len(matches)}"
    )
    return matches[0]


def _rule_prerequisites(target: str) -> tuple[str, ...]:
    """Return the parsed prerequisites for the sole `target` rule."""
    rules = _objects(_makefile_report().get("rules"), subject="rules")
    matches = [
        rule
        for rule in rules
        if target in _text_sequence(rule.get("targets"), subject="rule targets")
    ]
    assert len(matches) == 1, (
        f"expected one Makefile rule named {target!r}, found {len(matches)}"
    )
    return _text_sequence(matches[0].get("prerequisites"), subject="prerequisites")


def _variable_tokens(name: str) -> tuple[str, ...]:
    """Return shell-like tokens from Makeutil's raw variable value."""
    value = _sole_variable(name).get("raw_value")
    assert isinstance(value, str), f"expected {name!r} to have a string value"
    return tuple(shlex.split(value))


def _recipe_tokens(target: str) -> tuple[tuple[str, ...], ...]:
    """Return shell-like tokens for every recipe in `target`."""
    recipes = _objects(
        _sole_recipe_rule(target).get("recipes"), subject=f"{target} recipes"
    )
    return tuple(
        tuple(shlex.split(recipe_text.replace("\\\n", "")))
        for recipe in recipes
        if isinstance(recipe_text := recipe.get("text"), str)
    )


def _workflow_job(workflow_path: str, job_name: str) -> dict[str, object]:
    """Return the named job from a repository workflow."""
    workflow = yaml.safe_load((REPOSITORY_ROOT / workflow_path).read_text())
    workflow_mapping = _mapping(workflow, subject=f"{workflow_path} workflow")
    jobs = _mapping(workflow_mapping.get("jobs"), subject=f"{workflow_path} jobs")
    return _mapping(jobs.get(job_name), subject=f"{workflow_path} job {job_name!r}")


def _sole_workflow_step(
    job_name: str,
    step_name: str,
    *,
    workflow_path: str = ".github/workflows/ci.yml",
) -> dict[str, object]:
    """Return the sole named workflow step from `job_name`."""
    steps = _objects(
        _workflow_job(workflow_path, job_name).get("steps"),
        subject=f"{workflow_path} job {job_name!r} steps",
    )
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, (
        f"expected one {step_name!r} step in {workflow_path} job {job_name!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _run_skylos_allow(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a rejecting whitelist boundary without invoking Skylos itself."""
    environment: dict[str, str] = dict(os.environ)
    environment["NAME"] = "wsl-hostname"
    environment.pop("REASON", None)
    environment.pop("SYMBOL", None)
    return subprocess.run(  # noqa: S603 - fixed Make target and test arguments.
        (_executable_path("make"), "skylos-allow", *arguments),
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
    )


def _assert_makeutil_installation(command: object, *, contract: str) -> None:
    """Assert that `command` installs the pinned Makeutil parser."""
    assert isinstance(command, str), (
        f"{contract} must provide a Makeutil installation shell command"
    )
    assert (
        tuple(shlex.split(command.replace("\\\n", ""))) == _MAKEUTIL_INSTALL_TOKENS
    ), f"{contract} must pin the Makeutil installation command"


def test_lint_runs_the_strict_production_dead_code_gate() -> None:
    """`make lint` must delegate to Skylos's strict production-only scan."""
    assert "skylos" in _rule_prerequisites("lint"), (
        "make lint must depend on the Skylos dead-code target"
    )
    assert _variable_tokens("SKYLOS_VERSION") == ("4.33.2",), (
        "Skylos version contract must pin 4.33.2"
    )
    assert _variable_tokens("SKYLOS_PRODUCTION_TARGETS") == ("hecate",), (
        "Skylos production-target contract must scan hecate"
    )
    assert _variable_tokens("SKYLOS_EXCLUDE_FOLDERS") == ("tests",), (
        "Skylos exclusion contract must omit tests"
    )
    assert _recipe_tokens("skylos") == (
        (
            "$(SKYLOS)",
            "$(SKYLOS_PRODUCTION_TARGETS)",
            "--exclude",
            "$(SKYLOS_EXCLUDE_FOLDERS)",
            "--category",
            "dead_code",
            "--gate",
            "--format",
            "concise",
            "--no-upload",
            "--no-provenance",
            "--no-grep-verify",
        ),
    ), "Skylos production scan must retain its strict blocking and no-upload flags"


def test_skylos_cli_and_whitelist_dispatch_are_separate() -> None:
    """Scans and named exceptions must use their distinct command shapes."""
    assert _variable_tokens("SKYLOS_CLI") == (
        "$(UV_ENV)",
        "$(UV)",
        "tool",
        "run",
        "--python",
        "3.14",
        "--from",
        "skylos==$(SKYLOS_VERSION)",
        "skylos",
    ), "Skylos CLI must pin Python 3.14 and the pinned Skylos release"
    assert _variable_tokens("SKYLOS") == (
        "$(SKYLOS_CLI)",
        "--config-file",
        "pyproject.toml",
    ), "Skylos scan command must add only its configuration-file option"

    whitelist_commands = [
        command
        for command in _recipe_tokens("skylos-allow")
        if command[:1] == ("$(SKYLOS_CLI)",)
    ]
    assert whitelist_commands == [
        (
            "$(SKYLOS_CLI)",
            "whitelist",
            "$${SKYLOS_SYMBOL}",
            "--reason",
            "$${SKYLOS_REASON}",
        )
    ], "Skylos whitelist must dispatch before its symbol and --reason arguments"


def test_skylos_allow_requires_symbol_and_reason() -> None:
    """The helper must reject incomplete input before it can mutate TOML."""
    for arguments, expected_error in (
        ((), "Error: SYMBOL is required for a named whitelist exception"),
        (
            ("SYMBOL=handler",),
            "Error: REASON is required for a named whitelist exception",
        ),
    ):
        completed = _run_skylos_allow(*arguments)

        assert completed.returncode == 2, (
            "Skylos whitelist boundary must reject a missing required argument "
            f"for {arguments!r}"
        )
        assert expected_error in completed.stderr, (
            "Skylos whitelist boundary must identify the missing required "
            f"argument for {arguments!r}"
        )


def test_skylos_allow_dry_run_preserves_whitelist_argument_order() -> None:
    """Complete dry-run input must reveal, but not execute, the helper command."""
    completed = subprocess.run(  # noqa: S603 - fixed Make target and test arguments.
        (
            _executable_path("make"),
            "--dry-run",
            "skylos-allow",
            "SYMBOL=handler",
            "REASON=Loaded by plugin registry",
        ),
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
        text=True,
    )

    assert completed.returncode == 0, (
        "Skylos whitelist dry run must accept complete SYMBOL and REASON input"
    )
    assert (
        'skylos whitelist "${SKYLOS_SYMBOL}" --reason "${SKYLOS_REASON}"'
        in completed.stdout
    ), "Skylos whitelist dry run must preserve subcommand-before-reason order"


def test_skylos_configuration_models_only_verified_runtime_callers() -> None:
    """False positives must remain typed, precise entry points with reasons."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as configuration_file:
        configuration = tomllib.load(configuration_file)

    tool = _mapping(configuration.get("tool"), subject="tool configuration")
    skylos = _mapping(tool.get("skylos"), subject="Skylos configuration")
    gate = _mapping(skylos.get("gate"), subject="Skylos gate configuration")
    assert gate.get("strict") is True, (
        "Skylos gate configuration must enable strict mode"
    )
    dead_code = _mapping(
        skylos.get("dead_code"), subject="Skylos dead-code configuration"
    )
    entry_points = _objects(dead_code.get("entrypoints"), subject="Skylos entry points")

    entry_point_names = frozenset(
        name
        for entry_point in entry_points
        for name in _text_sequence(
            entry_point.get("full_name"), subject="Skylos entry-point full names"
        )
    )
    assert entry_point_names == _RUNTIME_METHOD_ENTRY_POINTS, (
        "Skylos entry points must list only the verified fully qualified methods"
    )
    for entry_point in entry_points:
        assert entry_point.get("type") == "method", (
            "Skylos entry points must classify Hecate runtime calls as methods"
        )
        reason = entry_point.get("reason")
        assert isinstance(reason, str), (
            "Skylos entry points must provide a textual runtime-caller reason"
        )
        assert reason, (
            "Skylos entry points must provide a non-empty runtime-caller reason"
        )

    whitelist = _mapping(skylos.get("whitelist"), subject="Skylos whitelist")
    documented = _mapping(
        whitelist.get("documented"), subject="documented Skylos whitelist"
    )
    assert not {"render", "to_dict", "expand_import"} & documented.keys(), (
        "common method names must not become global bare-name whitelist entries"
    )


def test_make_test_requires_makeutil() -> None:
    """The full suite must require its parser before collecting contracts."""
    assert "makeutil" in _rule_prerequisites("test"), (
        "make test must require Makeutil before running parser-backed contracts"
    )


def test_ci_runs_lint_and_bootstraps_makeutil_for_each_full_suite() -> None:
    """CI must retain lint failure propagation and parser provisioning."""
    lint_step = _sole_workflow_step(
        "lint-test", "Run lint gate, including Skylos dead-code detection"
    )
    assert lint_step.get("run") == "make lint", (
        "CI lint step must invoke the shared make lint target"
    )
    assert lint_step.get("continue-on-error") in {None, False}, (
        "CI lint step must not suppress a failing Skylos gate"
    )
    for workflow_path, job_name in (
        (".github/workflows/ci.yml", "lint-test"),
        (".github/workflows/coverage-main.yml", "coverage-upload"),
    ):
        job = _workflow_job(workflow_path, job_name)
        environment = _mapping(
            job.get("env"), subject=f"{workflow_path} Makeutil environment"
        )
        assert environment.get("MAKEUTIL_REVISION") == _MAKEUTIL_REVISION, (
            f"{workflow_path} {job_name} must pin the Makeutil revision"
        )
        assert environment.get("MAKEUTIL_TOOLCHAIN") == _MAKEUTIL_TOOLCHAIN, (
            f"{workflow_path} {job_name} must pin the Makeutil nightly toolchain"
        )
        parser_step = _sole_workflow_step(
            job_name, "Install Makefile parser", workflow_path=workflow_path
        )
        _assert_makeutil_installation(
            parser_step.get("run"),
            contract=f"{workflow_path} {job_name} Makeutil-install contract",
        )
