"""Observability contracts of the release workflow.

A release spans several jobs, so an operator follows it through the log lines
and the step summary rather than one job's output. These tests pin the
correlation fields, the summary columns, and the timing every publishing step
reports, so a step cannot quietly go back to a bare ``echo``. The workflow's
structural contracts live in ``test_release_workflow_contract.py``.
"""

from __future__ import annotations

import re
import typing as typ

from .ci_workflows import ROOT, jobs
from .release_workflow import WORKFLOW, step_script

_FETCH_INDEX = "Fetch the PyPI index"
_REPORT_HELPER = ROOT / "scripts" / "release_report.sh"
#: What a bare ``echo`` may write: a step output or the empty index, never a
#: diagnostic a person reads.
_STEP_PROTOCOL_SINK = re.compile(r'>>\s*"\$\{GITHUB_OUTPUT\}"|>\s*pypi-index\.json')


def _run_scripts(job_name: str) -> list[str]:
    """Return the ``run`` script of every step in ``job_name``."""
    declared = typ.cast("dict[str, object]", jobs(WORKFLOW)[job_name])
    steps = typ.cast("list[dict[str, object]]", declared["steps"])
    return [str(item.get("run", "")) for item in steps]


def test_every_index_read_writes_a_summary_row() -> None:
    """One row per read: job, attempt, status class, outcome, and elapsed."""
    script = step_script("publish-pypi", _FETCH_INDEX)
    assert step_script("publish-release", _FETCH_INDEX) == script, (
        "both jobs must report their index reads the same way"
    )
    for fragment in (
        ". scripts/release_report.sh",
        "elapsed=$((SECONDS - started))",
        'release_event fetch-index "${attempt}" "${status}" "${outcome}" "${elapsed}"',
    ):
        assert fragment in script, f"the index read must include {fragment!r}"


def test_the_release_summary_names_every_required_field() -> None:
    """The helper carries the columns, the correlation, and the record fields."""
    helper = _REPORT_HELPER.read_text(encoding="utf-8")
    for column in ("| Job |", "Attempt", "Status class", "Outcome", "Elapsed (s)"):
        assert column in helper, f"the summary must have a {column!r} column"
    for field in (
        "correlation=%s",
        "job=%s",
        "step=%s",
        "outcome=%s",
        "status_class=%s",
        "elapsed_s=%s",
    ):
        assert field in helper, f"a record must carry the {field!r} field"
    for variable in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        assert variable in helper, f"the correlation must come from {variable}"
    assert "GITHUB_STEP_SUMMARY" in helper, "the rows must reach the job summary"
    assert "$((SECONDS - started))" in helper, "every record must time its call"


def test_every_release_diagnostic_carries_the_correlation() -> None:
    """A bare ``echo`` would be a log line with no way back to its run."""
    for job_name in ("publish-pypi", "publish-release"):
        for script in _run_scripts(job_name):
            for line in script.splitlines():
                if not re.match(r"\s*echo\s", line):
                    continue
                assert _STEP_PROTOCOL_SINK.search(line), (
                    f"{job_name}: {line.strip()!r} must use release_log or "
                    "release_warn, so its line carries the run correlation"
                )


def test_the_publishing_steps_record_how_long_each_call_took() -> None:
    """The PyPI and GitHub calls report their outcome and elapsed seconds."""
    expected = {
        "publish-pypi": {
            "Skip artefacts already on PyPI": "release_run skip-pypi",
        },
        "publish-release": {
            "Note whether the release is a draft": "release_run draft-state",
            "List the release assets": "release_run list-assets",
            "Stage the assets the release lacks": "release_run stage-assets",
            "Check the fetched PyPI bytes": "release_run check-fetched",
            "Upload the assets the release lacks": "release_run upload-assets",
            "Check both destinations hold the same bytes": "release_run verify",
            "Publish the GitHub Release": "release_run publish",
        },
    }
    for job_name, wanted in expected.items():
        for name, fragment in wanted.items():
            script = step_script(job_name, name)
            assert ". scripts/release_report.sh" in script, (
                f"{name!r} must load the reporting helper"
            )
            assert fragment in script, f"{name!r} must run through {fragment!r}"
