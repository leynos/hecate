"""Makefile-parser and CI contracts for the contract suite itself."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess  # noqa: S404 - contract tests invoke fixed local tools.
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


def _executable_path(name: str) -> str:
    """Resolve a fixed executable required by this contract suite."""
    executable = shutil.which(name)
    assert executable is not None, (
        f"{name} must be available for the Makefile contracts"
    )
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


def test_make_test_requires_makeutil() -> None:
    """The full suite must require its parser before collecting contracts."""
    assert "makeutil" in _rule_prerequisites("test"), (
        "make test must require Makeutil before running parser-backed contracts"
    )


def test_ci_bootstraps_makeutil_for_each_full_suite() -> None:
    """CI must provision the pinned Makefile parser for each full suite."""
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
