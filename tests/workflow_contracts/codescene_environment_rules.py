"""Hold the CodeScene token's environment to the uploading job (CV-005).

The token lives in the `codescene` environment, whose deployment policy admits
`main` alone. So every job that invokes the uploader declares that
environment, no other job does, and no workflow a pull request can start
declares it in any job: a declaration there would let branch code ask for the
token.

The module composes the existing readers rather than restating them: the
workflows come from `loading.read_workflows`, the uploader is matched exactly
as `codescene_publisher.UPLOAD_ACTION`, and the pull-request surface is
`codescene_reach.pull_request_closure`, which already follows `./` and `$/`
calls and `workflow_run` chains.
"""

import typing as typ

from .codescene_publisher import UPLOAD_ACTION
from .codescene_reach import pull_request_closure
from .reading import jobs, steps

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from .loading import Document

ENVIRONMENT: typ.Final[str] = "codescene"
MISSING: typ.Final[str] = f"the uploading job must declare `environment: {ENVIRONMENT}`"
STRAY: typ.Final[str] = f"declares `{ENVIRONMENT}` but uploads nothing"
REACHABLE: typ.Final[str] = (
    f"is reachable from a pull request and declares `{ENVIRONMENT}`"
)


def environment_name(job: dict[str, object]) -> str | None:
    """Return the environment a job declares, from either accepted form.

    Returns
    -------
    str | None
        The environment's name, or None when the job declares none.

    Examples
    --------
    >>> environment_name({"environment": "codescene"})
    'codescene'
    >>> environment_name({"environment": {"name": "codescene", "url": "x"}})
    'codescene'
    >>> environment_name({}) is None
    True

    """
    match job.get("environment"):
        case str() as name:
            return name
        case {"name": str() as name}:
            return name
        case _:
            return None


def uploads(job: dict[str, object]) -> bool:
    """Return whether a job has a step invoking the shared uploader.

    The action path must match exactly, at any ref, as the publisher
    contract matches it, so a look-alike action does not count.

    Returns
    -------
    bool
        True when some step's `uses` names the upload action.

    Examples
    --------
    >>> uploads({"steps": [{"uses": f"{UPLOAD_ACTION}@v1"}]})
    True
    >>> uploads({"steps": [{"uses": f"{UPLOAD_ACTION}-check@v1"}]})
    False

    """
    return any(
        str(step.get("uses", "")).split("@", 1)[0] == UPLOAD_ACTION
        for step in steps(job)
    )


def _placed(
    documents: dict[str, Document], names: cabc.Iterable[str]
) -> list[tuple[str, dict[str, object]]]:
    """Return every job in the named workflows with its location.

    Returns
    -------
    list[tuple[str, dict[str, object]]]
        `"workflow:job"` and the job, for each job.

    """
    return [
        (f"{name}:{job_id}", job)
        for name in sorted(names)
        for job_id, job in jobs(documents[name]).items()
    ]


def environment_violations(
    documents: dict[str, Document], repository: str
) -> list[str]:
    """Report every departure from the `codescene` environment placement.

    Returns
    -------
    list[str]
        One message per violation; empty when the placement holds.

    """
    placed = _placed(documents, documents)
    uploading = [(where, job) for where, job in placed if uploads(job)]
    if not uploading:
        return ["no workflow job invokes the CodeScene uploader"]
    problems = [
        f"{where}: {MISSING}"
        for where, job in uploading
        if environment_name(job) != ENVIRONMENT
    ]
    problems.extend(
        f"{where} {STRAY}"
        for where, job in placed
        if not uploads(job) and environment_name(job) == ENVIRONMENT
    )
    closure = pull_request_closure(documents, repository)
    problems.extend(
        f"{where} {REACHABLE}"
        for where, job in _placed(documents, closure)
        if environment_name(job) == ENVIRONMENT
    )
    return problems
