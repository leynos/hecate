"""Drive a complete release run, then repeat it unchanged.

``test_release_reconciliation.py`` exercises the reconciliation cases one at a
time. This module runs the workflow's jobs in the order a tag push runs them --
version check, draft creation and snapshot, PyPI staging and publication,
GitHub staging, verification, and publication -- against the same ``gh`` and
``curl`` stand-ins, and then runs the whole sequence a second time against the
state the first run left behind.

The one interface that cannot run here is pypa's upload action, which is
modelled as copying the staged files to PyPI without overwriting. Everything
else is the checked-in step script, so the test pins the handoff between jobs:
the draft snapshot's ``github-state``, the ``release-dist`` artefacts, and the
digest check that must pass before the release becomes visible.
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


def _release_once(fake: FakeRelease, run: str, *, draft: bool) -> None:
    """Run the workflow's jobs in dependency order for one tag push."""
    version = scene.TAG.removeprefix("v")
    check = fake.root / f"check-version-{run}"
    check.mkdir()
    completed, stated = run_version_check(check, version, version)
    assert completed.returncode == 0, completed.stderr
    assert stated["prerelease"] == "false", f"{version} is not a pre-release"

    snapshot = scene.snapshot_release(fake, label=f"draft-release-{run}", create=True)
    scene.publish_pypi_from_snapshot(fake, snapshot, label=f"publish-pypi-{run}")
    scene.publish_release(
        fake,
        scene.ReleaseRun(
            label=f"publish-release-{run}",
            draft=draft,
            publish=True,
        ),
    )


def test_a_complete_release_publishes_and_a_rerun_uploads_nothing(
    fake: FakeRelease,
) -> None:
    """The first run publishes every name; the second changes no bytes."""
    for name in scene.ARTEFACTS:
        (fake.pypi / name).unlink(missing_ok=True)
        (fake.github / name).unlink(missing_ok=True)

    _release_once(fake, "first", draft=True)

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

    _release_once(fake, "rerun", draft=False)

    after = len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]])
    assert after == before, "a rerun of a published release must upload nothing"
    assert scene.holdings(fake.github) == published, (
        "a rerun must not change any asset's bytes"
    )
    assert scene.holdings(fake.pypi) == expected, "PyPI must be left untouched"
