"""Structural contracts of the release workflow.

These read the parsed workflow rather than executing it: which job holds which
token scope, what gates the upload, and in what order the release becomes
visible. The executed behaviour of the same steps lives in
``test_release_publish_steps.py`` and ``test_release_github_steps.py``; the
sweep over every ``run`` script in the repository lives in
``test_workflow_run_scripts.py``.
"""

from __future__ import annotations

import re
import typing as typ

from .ci_workflows import ROOT, jobs, workflow_document
from .release_workflow import WORKFLOW, step, step_script

_PINNED = re.compile(r"@[0-9a-f]{40}$")
_PYPROJECT_CHECK = "Check the pyproject.toml version against the tag"

#: Each job's exact token scopes. Only the GitHub Release jobs may write
#: repository contents, and only the attesting and uploading jobs may mint an
#: OpenID Connect token. `publish-pypi` reads contents only to check out
#: `scripts/`; it sees the draft through `draft-release`'s snapshot instead.
_EXPECTED_PERMISSIONS: typ.Final = {
    "check-version": {"contents": "read"},
    "build-wheels": {"contents": "read"},
    "attest": {"contents": "read", "id-token": "write", "attestations": "write"},
    "publish-pypi": {"contents": "read", "id-token": "write"},
    "draft-release": {"contents": "write"},
    "publish-release": {"contents": "write"},
}
_FETCH_INDEX = "Fetch the PyPI index"


def _job(name: str) -> dict[str, object]:
    """Return one release job."""
    return typ.cast("dict[str, object]", jobs(WORKFLOW)[name])


def _needs(name: str) -> set[str]:
    """Return every job ``name`` waits on, directly or transitively."""
    declared = _job(name).get("needs", [])
    direct = (
        {declared}
        if isinstance(declared, str)
        else set(typ.cast("list[str]", declared))
    )
    return direct.union(*(_needs(parent) for parent in direct))


def _declared_steps(job_name: str) -> list[dict[str, object]]:
    """Return one job's step mappings as the parsed document holds them."""
    declared = _job(job_name).get("steps", [])
    return typ.cast("list[dict[str, object]]", declared)


def _uses(job_name: str, prefix: str) -> dict[str, object]:
    """Return the single step of ``job_name`` that uses action ``prefix``."""
    found = [
        item
        for item in _declared_steps(job_name)
        if str(item.get("uses", "")).startswith(f"{prefix}@")
    ]
    assert len(found) == 1, f"{job_name} must use {prefix} exactly once"
    reference = typ.cast("str", found[0]["uses"])
    assert _PINNED.search(reference), f"{prefix} must be pinned by commit SHA"
    return found[0]


def test_every_job_holds_only_the_scopes_it_needs() -> None:
    """Nothing inherits a write scope from the top level."""
    assert workflow_document(WORKFLOW).get("permissions") == {}, (
        "release.yml must grant nothing at the top level"
    )
    declared = {name: _job(name).get("permissions") for name in jobs(WORKFLOW)}
    assert declared == _EXPECTED_PERMISSIONS, (
        "each job must declare exactly its own scopes"
    )


def test_every_action_the_release_uses_is_pinned_by_commit() -> None:
    """A mutable tag would let an action's code change under a release."""
    for job_name in jobs(WORKFLOW):
        for item in _declared_steps(job_name):
            reference = str(item.get("uses", ""))
            if reference and not reference.startswith("./"):
                assert _PINNED.search(reference), (
                    f"{job_name} uses {reference}, which is not a commit SHA"
                )


def test_checkouts_do_not_persist_the_token() -> None:
    """A checked-out repository must not keep a usable token on disk."""
    checkouts = [
        item
        for job_name in jobs(WORKFLOW)
        for item in _declared_steps(job_name)
        if str(item.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts, "the version check must check the repository out"
    for checkout in checkouts:
        declared = typ.cast("dict[str, object]", checkout["with"])
        assert declared["persist-credentials"] is False, (
            "a checkout must not leave a usable token on disk"
        )


def test_the_pypi_upload_runs_in_the_pypi_environment() -> None:
    """Trusted Publishing is bound to the protected ``pypi`` environment."""
    assert _job("publish-pypi")["environment"] == {
        "name": "pypi",
        "url": "https://pypi.org/project/hecate-enforce/",
    }, "the upload must run in the protected pypi environment"


def test_a_repushed_tag_queues_instead_of_cancelling() -> None:
    """A cancelled release could stop part-way through the upload."""
    concurrency = workflow_document(WORKFLOW)["concurrency"]
    assert concurrency == {
        "group": "release-${{ github.ref }}",
        "cancel-in-progress": False,
    }, "a re-pushed tag must queue behind the running release"


def test_the_index_lookup_retries_and_is_bounded() -> None:
    """Both index readers share one bounded, retrying, timed-out lookup."""
    script = step_script("publish-pypi", _FETCH_INDEX)
    assert step_script("publish-release", _FETCH_INDEX) == script, (
        "both jobs must run the same bounded lookup"
    )
    for fragment in (
        'while [ "${attempt}" -lt 6 ]; do',
        "--connect-timeout 10",
        "--max-time 60",
        "000|429|5??)",
        "attempts=%s",
        "https://pypi.org/simple/hecate-enforce/",
    ):
        assert fragment in script, f"the index lookup must include {fragment!r}"
    assert "404) echo '{\"files\": []}' > pypi-index.json ;;" in script, (
        "a project absent from PyPI must still read as an empty index"
    )


def test_every_publishing_job_waits_on_the_version_check() -> None:
    """No attestation, upload, or release happens for a mismatched tag."""
    assert _needs("publish-pypi") >= {"attest", "draft-release"}, (
        "PyPI needs the draft's snapshot to carry GitHub's bytes over"
    )
    assert "publish-pypi" in _needs("publish-release"), (
        "GitHub's missing assets take PyPI's bytes, so PyPI goes first"
    )
    for name in ("attest", "publish-pypi", "draft-release", "publish-release"):
        assert "check-version" in _needs(name), f"{name} must wait on check-version"
    pyproject = step("check-version", _PYPROJECT_CHECK)
    assert pyproject["env"] == {"TAG": "${{ github.ref_name }}"}, (
        "the pyproject check compares the tag with the declared version"
    )


def test_the_sdist_travels_with_the_wheel_into_attestation() -> None:
    """The release refuses a build that produced no sdist, or more than one."""
    collect = step_script("attest", "Collect release artefacts")
    assert "sdists=(dist/publish/*.tar.gz)" in collect, (
        "the collection must look for the sdist"
    )
    assert '"${#sdists[@]}" -ne 1' in collect, (
        "the collection must require exactly one sdist"
    )
    assert "Expected exactly one source distribution." in collect, (
        "the failure must name the sdist requirement"
    )
    assert "wheels=(dist/publish/*.whl)" in collect, (
        "the collection must look for the wheels"
    )
    assert "Unexpected files in the release artefact:" in collect, (
        "the collection must refuse anything else"
    )
    attest = _uses("attest", "actions/attest-build-provenance")
    assert attest["with"] == {"subject-path": "dist/publish/*"}, (
        "the attestation must cover every collected file"
    )


def test_the_published_artefacts_are_the_attested_ones() -> None:
    """Provenance covers every file, and later jobs ship exactly those bytes."""
    for name in ("publish-pypi", "draft-release", "publish-release"):
        assert "attest" in _needs(name), f"{name} must wait on the attestation"
        downloads = [
            item["with"]
            for item in _declared_steps(name)
            if str(item.get("uses", "")).startswith("actions/download-artifact@")
        ]
        assert {"name": "release-dist", "path": "dist"} in downloads, (
            f"{name} must take the attested artefact, not rebuilt files"
        )


def test_the_upload_keeps_pypi_attestations_and_is_idempotent() -> None:
    """PEP 740 attestations stay on, and a partial earlier upload is tolerated."""
    upload = _uses("publish-pypi", "pypa/gh-action-pypi-publish")
    assert upload["if"] == "steps.pending.outputs.remaining == 'true'", (
        "the upload must be skipped when nothing remains"
    )
    assert upload["with"] == {"packages-dir": "dist/publish/", "skip-existing": True}, (
        "the upload must tolerate a name PyPI already holds"
    )


def test_the_release_is_published_only_after_pypi() -> None:
    """A failed upload or a digest mismatch leaves the GitHub Release a draft."""
    assert {"draft-release", "publish-pypi"} <= _needs("publish-release"), (
        "the release must wait for the draft and the PyPI upload"
    )
    assert "--draft" in step_script(
        "draft-release", "Create or reuse the draft release"
    ), "the release must be created as a draft"
    names = [item.get("name") for item in _declared_steps("publish-release")]
    ordered = [
        "Note whether the release is a draft",
        "Upload the assets the release lacks",
        "Re-fetch the PyPI index",
        "Check both destinations hold the same bytes",
        "Publish the GitHub Release",
    ]
    for name in ordered:
        assert names.count(name) == 1, (
            f"{name!r} appears {names.count(name)} times; `index` would then "
            "compare one occurrence and leave the other unchecked"
        )
    positions = [names.index(name) for name in ordered]
    assert positions == sorted(positions), (
        "the draft state decides the upload; PyPI is re-read after it, so the "
        "digest check sees what the upload published, and both are compared "
        "before the release"
    )
    # GitHub stops a job at its first failing step unless that step carries an
    # `if`. Plain sequencing therefore gates publication on the digest check;
    # any condition here could skip the check and still publish.
    for name in (
        "Check both destinations hold the same bytes",
        "Publish the GitHub Release",
    ):
        assert "if" not in step("publish-release", name), (
            f"{name!r} must run unconditionally, or a conditional could bypass "
            "the digest check and publish a release the check never inspected"
        )
    assert "--draft=false" in step_script(
        "publish-release", "Publish the GitHub Release"
    ), "publication must un-draft the release"


def test_the_attestation_bundle_is_named_by_the_tag() -> None:
    """A per-run bundle name would add an asset on every re-run.

    The release must upload nothing the second time a tag is pushed, so the
    bundle's name may depend only on the tag, never on the run or its attempt.
    """
    script = step_script("attest", "Stage the provenance bundle")
    assert "hecate-enforce-${GITHUB_REF_NAME}.sigstore.json" in script, (
        "the bundle must be named after the tag alone"
    )
    for per_run in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        assert per_run not in script, (
            f"a bundle named with {per_run} cannot converge across re-runs"
        )


def test_every_scripts_checkout_is_sparse_and_credential_free() -> None:
    """The jobs that run `scripts/` fetch it and nothing else."""
    for name in ("attest", "draft-release", "publish-pypi", "publish-release"):
        checkout = _uses(name, "actions/checkout")
        assert checkout["with"] == {
            "persist-credentials": False,
            "sparse-checkout": "scripts\n",
        }, f"{name} must check out only what its steps run"


def test_the_release_workflow_has_no_telemetry_action() -> None:
    """Cuprum's telemetry action has no place in this release."""
    document = (ROOT / ".github" / "workflows" / WORKFLOW).read_text(encoding="utf-8")
    assert "release-telemetry" not in document, (
        "the release has no telemetry action to feed"
    )
