"""Behavioural tests for ``scripts/release_report.sh``.

``test_release_report_contract.py`` reads the helper's text and the workflow's
steps, which proves a function is present but not that it works. These tests
source the helper in a scratch directory and run it, then assert on the real
standard output, standard error, and job summary a publishing step produces.
"""

from __future__ import annotations

import shlex
import typing as typ

import pytest

from .ci_workflows import ROOT
from .release_workflow import run_bash

if typ.TYPE_CHECKING:
    import pathlib as pth
    import subprocess

_HELPER = ROOT / "scripts" / "release_report.sh"
_HEADING = "## Release run"
_COLUMNS = "| Job | Step | Attempt | Status class | Outcome | Elapsed (s) |"
_ENVIRONMENT = {
    "GITHUB_JOB": "publish-release",
    "GITHUB_RUN_ID": "4711",
    "GITHUB_RUN_ATTEMPT": "2",
}


def _run(tmp_path: pth.Path, *lines: str) -> subprocess.CompletedProcess[str]:
    """Run ``lines`` under Bash after sourcing the helper in ``tmp_path``.

    The summary is written to ``tmp_path/summary.md``, as the workflow writes
    it to ``GITHUB_STEP_SUMMARY``.
    """
    script = "\n".join([f". {shlex.quote(str(_HELPER))}", *lines])
    summary = tmp_path / "summary.md"
    return run_bash(
        script, tmp_path, {**_ENVIRONMENT, "GITHUB_STEP_SUMMARY": str(summary)}
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("200", "2xx"),
        ("301", "3xx"),
        ("404", "4xx"),
        ("503", "5xx"),
        ("000", "none"),
        ("", "none"),
    ],
    ids=["success", "redirect", "client-error", "server-error", "no-response", "empty"],
)
def test_the_status_class_bounds_each_response_family(
    tmp_path: pth.Path, status: str, expected: str
) -> None:
    """A summary row names the status class, never the bare code."""
    result = _run(tmp_path, f"release_status_class {shlex.quote(status)}")

    assert result.stdout == expected, (
        "the class must be derived from the status, and a status that is no "
        "response at all must degrade to none"
    )


def test_a_failing_command_is_recorded_and_its_failure_kept(
    tmp_path: pth.Path,
) -> None:
    """The wrapped failure must be reported and must fail the step."""
    result = _run(tmp_path, "release_run fetch-index false")

    assert result.returncode != 0, "the wrapped failure must reach the step"
    assert (
        "release-event job=publish-release step=fetch-index outcome=failed "
        "status_class=none elapsed_s=" in result.stderr
    ), "the record must name the failed step and its outcome"
    assert "correlation=4711/2" in result.stderr, (
        "the record must carry the run correlation"
    )


def test_a_succeeding_command_is_recorded_and_allowed(tmp_path: pth.Path) -> None:
    """The wrapped success must record ok and leave the step green."""
    result = _run(tmp_path, "release_run fetch-index true")

    assert result.returncode == 0, "a wrapped success must not fail the step"
    assert "step=fetch-index outcome=ok" in result.stderr, (
        "the record must name the successful step"
    )


def test_each_event_appends_one_heading_and_one_row(tmp_path: pth.Path) -> None:
    """Two index reads share one heading and add one row each."""
    result = _run(
        tmp_path,
        "release_event fetch-index 1 200 ok 3",
        "release_event fetch-index 2 404 failed 4",
    )

    assert result.returncode == 0, "recording an event must not fail the step"
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary.count(_HEADING) == 1, "the heading must be written once per job"
    assert _COLUMNS in summary, "the summary must name every column"
    rows = [
        line for line in summary.splitlines() if line.startswith("| publish-release |")
    ]
    assert rows == [
        "| publish-release | fetch-index | 1 | 2xx | ok | 3 |",
        "| publish-release | fetch-index | 2 | 4xx | failed | 4 |",
    ], "each call must add one row carrying that read's values"


def test_a_record_names_every_field_with_the_run_correlation(
    tmp_path: pth.Path,
) -> None:
    """The record is the machine-readable half of the report."""
    result = _run(tmp_path, "release_record list-assets ok 2xx 7")

    assert not result.stdout, "a record belongs on standard error"
    assert result.stderr.strip() == (
        "release-event job=publish-release step=list-assets outcome=ok "
        "status_class=2xx elapsed_s=7 correlation=4711/2"
    ), "the record must carry every field with the run's values"
