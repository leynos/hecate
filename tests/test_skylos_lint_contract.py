"""Contracts for the blocking Skylos lint and CI boundary."""

from __future__ import annotations

import re
import tomllib
import typing as typ
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = REPOSITORY_ROOT / "Makefile"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_ENTRY_POINTS = {
    "hecate.diagnostics.IgnoredImportDiagnostic.render",
    "hecate.diagnostics.IgnoredImportDiagnostic.to_dict",
    "hecate.reexports.ReexportIndex.expand_import",
}


def _load_project_config() -> dict[str, object]:
    """Load the repository TOML configuration."""
    project_config = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert isinstance(project_config, dict), "pyproject.toml must be a mapping"
    return project_config


def _skylos_config() -> dict[str, object]:
    """Return the configured Skylos policy."""
    tool = _load_project_config().get("tool")
    assert isinstance(tool, dict), "pyproject.toml must define [tool]"
    skylos = tool.get("skylos")
    assert isinstance(skylos, dict), "pyproject.toml must define [tool.skylos]"
    return typ.cast("dict[str, object]", skylos)


def _skylos_command() -> str:
    """Return the normalized Skylos recipe from the Makefile."""
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^skylos: build ## Detect dead production code\n"
        r"(?P<command>(?:\t[^\n]*(?:\n|$))+)",
        makefile,
        flags=re.MULTILINE,
    )
    assert match is not None, "Makefile must define the Skylos lint target"
    return " ".join(match.group("command").split())


def test_lint_target_requires_skylos() -> None:
    """The top-level lint gate must run Skylos."""
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(r"^lint: (?P<dependencies>[^\n#]+)", makefile, re.MULTILINE)
    assert match is not None, "Makefile must define the lint target"
    assert "skylos" in match.group("dependencies").split(), (
        "make lint must depend on the Skylos target"
    )


def test_skylos_target_is_blocking_local_production_scan() -> None:
    """The Skylos target must retain its reviewed gate arguments."""
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    command = _skylos_command()

    assert "SKYLOS_VERSION ?= 4.33.2" in makefile
    assert "--config-file pyproject.toml" in makefile
    assert "SKYLOS_PRODUCTION_TARGETS ?= hecate" in makefile
    assert "$(SKYLOS) $(SKYLOS_PRODUCTION_TARGETS)" in command
    assert "--category dead_code" in command
    assert "--gate" in command
    assert "--format concise" in command
    assert "--no-upload" in command
    assert "--no-provenance" in command
    assert "--no-grep-verify" in command


def test_skylos_false_positives_are_scoped_entry_points() -> None:
    """Only the verified false positives may bypass Skylos liveness checks."""
    skylos = _skylos_config()
    dead_code = skylos.get("dead_code")
    assert isinstance(dead_code, dict), "Skylos must configure dead-code policy"
    entrypoints = dead_code.get("entrypoints")
    assert isinstance(entrypoints, list), "Skylos must define typed entry points"

    configured_entry_points: set[str] = set()
    for entrypoint in entrypoints:
        if not isinstance(entrypoint, dict) or entrypoint.get("type") != "method":
            continue
        full_names = entrypoint.get("full_name")
        if not isinstance(full_names, list):
            continue
        configured_entry_points.update(
            full_name for full_name in full_names if isinstance(full_name, str)
        )
    assert configured_entry_points >= EXPECTED_ENTRY_POINTS

    whitelist = skylos.get("whitelist")
    assert isinstance(whitelist, dict), "Skylos must define a whitelist policy"
    documented = whitelist.get("documented", {})
    assert isinstance(documented, dict), "Skylos whitelist entries must be named"
    assert not {"render", "to_dict", "expand_import"} & documented.keys(), (
        "common method names must use scoped typed entry points, not the "
        "bare-name whitelist"
    )


def test_ci_runs_lint_without_suppressing_failure() -> None:
    """CI must propagate the complete local lint gate's exit status."""
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "CI workflow must be a mapping"
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "CI workflow must define jobs"
    lint_test = jobs.get("lint-test")
    assert isinstance(lint_test, dict), "CI workflow must define the lint-test job"
    steps = lint_test.get("steps")
    assert isinstance(steps, list), "lint-test must define steps"

    lint_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("run") == "make lint"
    ]
    assert len(lint_steps) == 1, "CI must run make lint exactly once"
    assert lint_steps[0].get("continue-on-error") in {None, False}, (
        "CI must not suppress a failing Skylos lint gate"
    )
