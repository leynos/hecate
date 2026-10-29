"""Makefile and CI contracts for the Skylos dead-code gate."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess  # noqa: S404 - contract tests invoke fixed local tools.
import tomllib
import typing as typ
from pathlib import Path

import yaml
from json_shape_fixtures import mapping, objects, text_sequence

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
_SKYLOS_VERSION_TOKENS: typ.Final = ("4.33.2",)
_SKYLOS_PRODUCTION_TARGET_TOKENS: typ.Final = ("hecate",)
_SKYLOS_EXCLUDE_FOLDER_TOKENS: typ.Final = ("tests",)
_SKYLOS_ALLOW_LOCK_TOKENS: typ.Final = (".skylos-whitelist.lock",)
_SKYLOS_CLI_TOKENS: typ.Final = (
    "$(UV_ENV)",
    "$(UV)",
    "tool",
    "run",
    "--python",
    "3.14",
    "--from",
    "skylos==$(SKYLOS_VERSION)",
    "skylos",
)
_SKYLOS_SCAN_MACRO_TOKENS: typ.Final = (
    "$(SKYLOS_CLI)",
    "--config-file",
    "pyproject.toml",
)
_SKYLOS_SCAN_RECIPE_TOKENS: typ.Final = (
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
)
_SKYLOS_WHITELIST_RECIPE_TOKENS: typ.Final = (
    "@(",
    "flock",
    "9",
    "||",
    "exit;",
    "$(SKYLOS_CLI)",
    "whitelist",
    "$${SKYLOS_SYMBOL}",
    "--reason",
    "$${SKYLOS_REASON}",
    ")",
    "9>$(SKYLOS_ALLOW_LOCK)",
)
_RUNTIME_ENTRY_POINTS: typ.Final[dict[str, frozenset[str]]] = {
    "method": frozenset({
        "hecate.diagnostics.CoverageDiagnostic.render",
        "hecate.diagnostics.CoverageDiagnostic.to_dict",
        "hecate.diagnostics.IgnoredImportDiagnostic.render",
        "hecate.diagnostics.IgnoredImportDiagnostic.to_dict",
        "hecate.origins.OriginIndex.origins_for",
    }),
    # Skylos reads a derived TypedDict's fields as variables, not annotations,
    # so this keyword reaches the scanner as a misleadingly "unused" variable.
    "variable": frozenset({"hecate.output.JsonRenderOptions.include_unclassified"}),
}
_DOCUMENTED_WHITELIST_NAMES: typ.Final = frozenset[str]()


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
    parse = mapping(report.get("parse"), subject="Makeutil parse report")
    assert parse.get("status") == "complete", (
        f"makeutil did not complete the Makefile parse: {parse!r}"
    )
    return report


def _sole_variable(name: str) -> dict[str, object]:
    """Return Makeutil's sole variable fact for `name`."""
    variables = objects(_makefile_report().get("variables"), subject="variables")
    matches = [variable for variable in variables if variable.get("name") == name]
    assert len(matches) == 1, (
        f"expected one Makefile variable named {name!r}, found {len(matches)}"
    )
    return matches[0]


def _sole_recipe_rule(target: str) -> dict[str, object]:
    """Return the sole parsed `target` rule containing recipes."""
    rules = objects(_makefile_report().get("rules"), subject="rules")
    matches = [
        rule
        for rule in rules
        if target in text_sequence(rule.get("targets"), subject="rule targets")
        and objects(rule.get("recipes"), subject="rule recipes")
    ]
    assert len(matches) == 1, (
        f"expected one recipe-bearing Makefile rule named {target!r}, found "
        f"{len(matches)}"
    )
    return matches[0]


def _rule_prerequisites(target: str) -> tuple[str, ...]:
    """Return the parsed prerequisites for the sole `target` rule."""
    rules = objects(_makefile_report().get("rules"), subject="rules")
    matches = [
        rule
        for rule in rules
        if target in text_sequence(rule.get("targets"), subject="rule targets")
    ]
    assert len(matches) == 1, (
        f"expected one Makefile rule named {target!r}, found {len(matches)}"
    )
    return text_sequence(matches[0].get("prerequisites"), subject="prerequisites")


def _variable_tokens(name: str) -> tuple[str, ...]:
    """Return shell-like tokens from Makeutil's raw variable value."""
    value = _sole_variable(name).get("raw_value")
    assert isinstance(value, str), f"expected {name!r} to have a string value"
    return tuple(shlex.split(value))


def _recipe_tokens(target: str) -> tuple[tuple[str, ...], ...]:
    """Return shell-like tokens for every recipe in `target`."""
    recipes = objects(
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
    workflow_mapping = mapping(workflow, subject=f"{workflow_path} workflow")
    jobs = mapping(workflow_mapping.get("jobs"), subject=f"{workflow_path} jobs")
    return mapping(jobs.get(job_name), subject=f"{workflow_path} job {job_name!r}")


def _sole_workflow_step(
    job_name: str,
    step_name: str,
    *,
    workflow_path: str = ".github/workflows/ci.yml",
) -> dict[str, object]:
    """Return the sole named workflow step from `job_name`."""
    steps = objects(
        _workflow_job(workflow_path, job_name).get("steps"),
        subject=f"{workflow_path} job {job_name!r} steps",
    )
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, (
        f"expected one {step_name!r} step in {workflow_path} job {job_name!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


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
    assert _variable_tokens("SKYLOS_VERSION") == _SKYLOS_VERSION_TOKENS, (
        "Skylos version contract must pin 4.33.2"
    )
    assert (
        _variable_tokens("SKYLOS_PRODUCTION_TARGETS")
        == _SKYLOS_PRODUCTION_TARGET_TOKENS
    ), "Skylos production-target contract must scan hecate"
    assert (
        _variable_tokens("SKYLOS_EXCLUDE_FOLDERS") == _SKYLOS_EXCLUDE_FOLDER_TOKENS
    ), "Skylos exclusion contract must omit tests"
    assert _recipe_tokens("skylos") == _SKYLOS_SCAN_RECIPE_TOKENS, (
        "Skylos production scan must retain its strict blocking and no-upload flags"
    )


def test_skylos_cli_and_whitelist_dispatch_are_separate() -> None:
    """Scans and named exceptions must use their distinct command shapes."""
    assert _variable_tokens("SKYLOS_CLI") == _SKYLOS_CLI_TOKENS, (
        "Skylos CLI must pin Python 3.14 and the pinned Skylos release"
    )
    assert _variable_tokens("SKYLOS") == _SKYLOS_SCAN_MACRO_TOKENS, (
        "Skylos scan command must add only its configuration-file option"
    )
    assert _variable_tokens("SKYLOS_ALLOW_LOCK") == _SKYLOS_ALLOW_LOCK_TOKENS, (
        "Skylos allow-list helper must use the ignored repository-local lock file"
    )

    whitelist_commands = [
        command
        for command in _recipe_tokens("skylos-allow")
        if "$(SKYLOS_CLI)" in command
    ]
    assert whitelist_commands == [_SKYLOS_WHITELIST_RECIPE_TOKENS], (
        "Skylos whitelist must serialize its documented update before dispatch"
    )


def _entry_points_by_kind(
    entry_points: list[dict[str, object]],
) -> dict[str, frozenset[str]]:
    """Return each declared entry point grouped by the kind Skylos reports.

    The kind is part of an exception's precision: flattening the names would let
    an entry declared for the wrong kind satisfy the reviewed set while matching
    nothing, or matching more than the reviewed symbol.
    """
    names_by_kind: dict[str, set[str]] = {}
    for entry_point in entry_points:
        kind = entry_point.get("type")
        assert isinstance(kind, str), (
            "Skylos entry points must declare the kind of definition they exempt"
        )
        assert kind in _RUNTIME_ENTRY_POINTS, (
            f"Skylos entry points must not exempt {kind!r} definitions"
        )
        reason = entry_point.get("reason")
        assert isinstance(reason, str), (
            "Skylos entry points must provide a textual runtime-caller reason"
        )
        assert reason, (
            "Skylos entry points must provide a non-empty runtime-caller reason"
        )
        names_by_kind.setdefault(kind, set()).update(
            text_sequence(
                entry_point.get("full_name"), subject="Skylos entry-point full names"
            )
        )
    return {kind: frozenset(names) for kind, names in names_by_kind.items()}


def test_skylos_configuration_models_only_verified_runtime_callers() -> None:
    """False positives must remain typed, precise entry points with reasons."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as configuration_file:
        configuration = tomllib.load(configuration_file)

    tool = mapping(configuration.get("tool"), subject="tool configuration")
    skylos = mapping(tool.get("skylos"), subject="Skylos configuration")
    gate = mapping(skylos.get("gate"), subject="Skylos gate configuration")
    assert gate.get("strict") is True, (
        "Skylos gate configuration must enable strict mode"
    )
    dead_code = mapping(
        skylos.get("dead_code"), subject="Skylos dead-code configuration"
    )
    entry_points = objects(dead_code.get("entrypoints"), subject="Skylos entry points")

    assert _entry_points_by_kind(entry_points) == _RUNTIME_ENTRY_POINTS, (
        "Skylos entry points must list only the verified runtime callers of each kind"
    )

    whitelist = mapping(skylos.get("whitelist"), subject="Skylos whitelist")
    documented = mapping(
        whitelist.get("documented"), subject="documented Skylos whitelist"
    )
    assert frozenset(documented) == _DOCUMENTED_WHITELIST_NAMES, (
        "documented Skylos whitelist names must match the consciously reviewed set"
    )


def test_skylos_allow_lock_is_ignored() -> None:
    """The serialized allow-list lock must remain repository-local state."""
    completed = subprocess.run(  # noqa: S603 - fixed Git check-ignore command.
        (
            _executable_path("git"),
            "check-ignore",
            "--quiet",
            _SKYLOS_ALLOW_LOCK_TOKENS[0],
        ),
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    assert completed.returncode == 0, (
        "Skylos allow-list lock must be ignored as repository-local state"
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
        environment = mapping(
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
