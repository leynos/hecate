"""Prove the `codescene` environment sits on the uploading job alone.

Each test mutates a copy of this repository's workflows the way a later edit
could, and asserts the clause meant to catch it does. The check step, the ref
guard and `access-token:` stay held by the existing CV-005 contract.
"""

import copy
import typing as typ
from pathlib import Path

import pytest

from .codescene_environment_rules import (
    MISSING,
    REACHABLE,
    STRAY,
    environment_violations,
)
from .codescene_publisher import UPLOAD_ACTION
from .codescene_reach import pull_request_closure
from .loading import Document, read_workflows
from .reading import jobs

WORKFLOWS: typ.Final[Path] = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows"
)
REPOSITORY: typ.Final[str] = "leynos/hecate"
PUBLISHER: typ.Final[str] = "coverage-main.yml"
LANE: typ.Final[str] = "ci.yml"


@pytest.fixture
def workflows() -> dict[str, Document]:
    """Return a private copy of the repository's workflows to mutate.

    Returns
    -------
    dict[str, Document]
        The parsed workflows, read afresh for this test alone.

    """
    return copy.deepcopy(read_workflows(WORKFLOWS))


def _first_job(workflows: dict[str, Document], name: str) -> dict[str, object]:
    """Return one workflow's first job, for mutation in place.

    Returns
    -------
    dict[str, object]
        The job mapping.

    """
    return next(iter(jobs(workflows[name]).values()))


def _add_job(
    workflows: dict[str, Document], name: str, job_id: str, job: object
) -> None:
    """Add one job to a workflow, for mutation in place."""
    typ.cast("dict[object, object]", workflows[name]["jobs"])[job_id] = job


def _reports(workflows: dict[str, Document], fragment: str) -> None:
    """Fail unless the rule reports a violation containing `fragment`."""
    found = environment_violations(workflows, REPOSITORY)
    assert any(fragment in problem for problem in found), (
        f"expected a violation naming {fragment!r}, got {found}"
    )


def test_repository_places_the_environment(workflows: dict[str, Document]) -> None:
    """The publisher declares the environment and nothing else does."""
    found = environment_violations(workflows, REPOSITORY)
    assert not found, f"expected no violations, got {found}"


def test_the_pull_request_lane_is_read(workflows: dict[str, Document]) -> None:
    """The closure reaches the lane, so the third clause has something to read."""
    reached = pull_request_closure(workflows, REPOSITORY)
    assert LANE in reached, f"{LANE} must be read as pull-request reachable: {reached}"


def test_publisher_cannot_drop_the_environment(workflows: dict[str, Document]) -> None:
    """Without it the moved token never reaches the upload, which then skips."""
    del _first_job(workflows, PUBLISHER)["environment"]
    _reports(workflows, MISSING)


def test_publisher_cannot_name_another_environment(
    workflows: dict[str, Document],
) -> None:
    """Another environment holds no CodeScene token."""
    _first_job(workflows, PUBLISHER)["environment"] = "production"
    _reports(workflows, MISSING)


def test_mapping_form_is_accepted(workflows: dict[str, Document]) -> None:
    """`{name: codescene}` is the same declaration as the bare string."""
    _first_job(workflows, PUBLISHER)["environment"] = {"name": "codescene"}
    found = environment_violations(workflows, REPOSITORY)
    assert not found, f"the mapping form must be accepted, got {found}"


def test_no_other_job_may_declare_it(workflows: dict[str, Document]) -> None:
    """A second holder of the token widens what can read it."""
    _add_job(
        workflows,
        PUBLISHER,
        "other",
        {"environment": "codescene", "steps": [{"run": "true"}]},
    )
    _reports(workflows, STRAY)


def test_a_look_alike_action_is_not_the_uploader(
    workflows: dict[str, Document],
) -> None:
    """Only the shared uploader's exact path earns the environment."""
    look_alike = {"uses": f"{UPLOAD_ACTION}-check@v1"}
    _add_job(
        workflows,
        PUBLISHER,
        "other",
        {"environment": "codescene", "steps": [look_alike]},
    )
    _reports(workflows, f"{PUBLISHER}:other {STRAY}")


def test_no_pull_request_job_may_declare_it(workflows: dict[str, Document]) -> None:
    """A pull request's own code must never be able to request the token."""
    _first_job(workflows, LANE)["environment"] = {"name": "codescene"}
    _reports(workflows, REACHABLE)


@pytest.mark.parametrize("prefix", ["./", "$/"])
def test_a_called_workflow_is_read_too(
    workflows: dict[str, Document], prefix: str
) -> None:
    """A workflow the lane calls runs for the pull request as well."""
    workflows["called.yml"] = {
        "on": {"workflow_call": None},
        "jobs": {"inner": {"environment": "codescene", "steps": [{"run": "true"}]}},
    }
    _add_job(
        workflows, LANE, "forward", {"uses": f"{prefix}.github/workflows/called.yml"}
    )
    _reports(workflows, f"called.yml:inner {REACHABLE}")


def test_a_workflow_run_chain_is_read_too(workflows: dict[str, Document]) -> None:
    """A run chained after the lane holds secrets, so it is pull-request surface."""
    workflows["after.yml"] = {
        "on": {"workflow_run": {"workflows": ["CI"], "types": ["completed"]}},
        "jobs": {"inner": {"environment": "codescene", "steps": [{"run": "true"}]}},
    }
    _reports(workflows, f"after.yml:inner {REACHABLE}")


def test_an_empty_reading_is_refused(workflows: dict[str, Document]) -> None:
    """With no uploader left the rule says so rather than passing."""
    job = _first_job(workflows, PUBLISHER)
    job["steps"] = [
        step
        for step in typ.cast("list[dict[object, object]]", job["steps"])
        if UPLOAD_ACTION not in str(step.get("uses", ""))
    ]
    _reports(workflows, "no workflow job invokes")
