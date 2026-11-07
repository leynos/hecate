"""Drive a complete release run, then repeat it unchanged.

``test_release_reconciliation.py`` exercises the reconciliation cases one at a
time. This module runs the workflow's jobs in the order a tag push runs them --
version check, build, draft creation and snapshot, PyPI staging and
publication, GitHub staging, verification, and publication -- against the same
``gh`` and ``curl`` stand-ins, and then runs the whole sequence a second time
against the state the first run left behind.

Each job starts from the ``dist`` directory the previous job uploaded, as the
``release-dist`` artefact does, so a broken hand-off path fails here rather
than in a tag run, and the bytes each job hands on are compared with the ones
the build produced.

What this cannot cover, and what only a tag run can:

- the hosted runner's own wiring -- ``actions/upload-artifact`` and
  ``download-artifact``, the ``needs`` graph GitHub enforces, and the
  composite ``actions/attest-build-provenance`` step;
- PyPI Trusted Publishing: the OIDC token exchange and pypa's upload action,
  which this module replaces with a copy that refuses to overwrite;
- ``gh release upload`` against the real API, and a real CDN's index latency.

The job order and the permission scopes are pinned separately by
``test_release_workflow_contract.py``; here the checked-in step scripts run.
"""

from __future__ import annotations

import sys

import pytest

from . import release_scenario as scene
from .release_workflow import FakeRelease, run_version_check

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


def _release_once(fake: FakeRelease, run: str, *, draft: bool) -> bool:
    """Run the workflow's jobs in dependency order for one tag push.

    Returns whether ``publish-pypi`` told the workflow that artefacts remained,
    which is the condition its upload step reads.
    """
    version = scene.TAG.removeprefix("v")
    check = fake.root / f"check-version-{run}"
    check.mkdir()
    completed, stated = run_version_check(check, version, version)
    assert completed.returncode == 0, completed.stderr
    assert stated["prerelease"] == "false", f"{version} is not a pre-release"

    # The build job uploads `release-dist`; every later job downloads it and
    # works from those bytes alone.
    dist = scene.job_directory(fake, "build", label=f"build-{run}")[0] / "dist"
    expected = {name: scene.local(name) for name in scene.ARTEFACTS}

    snapshot = scene.snapshot_release(
        fake, label=f"draft-release-{run}", create=True, dist_from=dist
    )
    assert scene.holdings(snapshot / "dist" / "publish") == expected, (
        "draft-release must receive the build job's artefacts unchanged"
    )

    remaining = scene.publish_pypi_from_snapshot(
        fake, snapshot, label=f"publish-pypi-{run}", dist_from=dist
    )

    published = scene.publish_release(
        fake,
        scene.ReleaseRun(
            label=f"publish-release-{run}",
            draft=draft,
            publish=True,
            dist_from=dist,
        ),
    )
    assert scene.holdings(published / "dist" / "publish") == expected, (
        "publish-release must receive the build job's artefacts unchanged"
    )
    return remaining


def test_a_complete_release_publishes_and_a_rerun_uploads_nothing(
    fake: FakeRelease,
) -> None:
    """The first run publishes every name; the second changes no bytes."""
    for name in scene.ARTEFACTS:
        (fake.pypi / name).unlink(missing_ok=True)
        (fake.github / name).unlink(missing_ok=True)

    assert _release_once(fake, "first", draft=True), (
        "a first release must tell the workflow to upload"
    )

    expected = {name: scene.local(name) for name in scene.ARTEFACTS}
    assert scene.holdings(fake.pypi) == expected, (
        "PyPI must hold this run's bytes for every name"
    )
    assert scene.holdings(fake.github) == {**expected, scene.BUNDLE: b"bundle"}, (
        "the release must ship the same bytes plus the bundle it attests"
    )
    edits = [call for call in fake.calls("gh") if call[:2] == ["release", "edit"]]
    assert edits, "the run must un-draft the release once everything agrees"
    assert any("--draft=false" in call for call in edits), (
        "publication is the step that makes the release visible"
    )

    before = len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]])
    published = scene.holdings(fake.github)

    assert not _release_once(fake, "rerun", draft=False), (
        "a rerun must tell the workflow that no artefact remains"
    )

    after = len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]])
    assert after == before, "a rerun of a published release must upload nothing"
    assert scene.holdings(fake.github) == published, (
        "a rerun must not change any asset's bytes"
    )
    assert scene.holdings(fake.pypi) == expected, "PyPI must be left untouched"
