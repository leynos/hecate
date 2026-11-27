"""Re-running a release that both destinations already hold.

The acceptance criterion is that pushing the same tag again uploads nothing,
adds no second provenance bundle, and overwrites nothing. These tests run the
checked-in steps twice, or seed both destinations as a completed first run
would leave them, and assert that the second pass is a no-op. The staging and
reconciliation helpers they share live in ``release_scenario.py``.
"""

from __future__ import annotations

import shutil
import sys

import pytest

from . import release_scenario as scene
from .release_workflow import FakeRelease, outputs

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


def test_a_rerun_after_success_uploads_nothing(fake: FakeRelease) -> None:
    """A second complete run finds every name on both sides and changes nothing."""
    scene.draft_and_publish_pypi(fake)
    scene.publish_release(fake)
    before = (scene.holdings(fake.pypi), scene.holdings(fake.github))
    for job in ("draft-release", "publish-pypi", "publish-release"):
        shutil.rmtree(fake.root / job)
    # Forget the first run's calls: the assertions below are about the second.
    (fake.root / "calls.jsonl").unlink()

    # The first run published the release, so the second one starts from a
    # public release; its own draft check is what keeps the bundle off it.
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    env.update(FAKE_RELEASE_DRAFT="false")
    for name in scene.PUBLISH_STEPS:
        scene.run_required("publish-release", name, cwd, env)
    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )

    assert (scene.holdings(fake.pypi), scene.holdings(fake.github)) == before, (
        "a complete re-run must leave both destinations unchanged"
    )
    assert outputs(fake.root / "publish-pypi" / "output")["remaining"] == "false", (
        "PyPI must have nothing left to upload"
    )
    assert outputs(cwd / "output")["pending"] == "false", (
        "the release must have nothing left to upload"
    )
    uploads = [call for call in fake.calls("gh") if call[:2] == ["release", "upload"]]
    assert uploads == [], "a complete re-run uploads nothing, bundle included"


def test_a_pypi_only_name_uploads_when_the_bundle_is_already_attached(
    fake: FakeRelease,
) -> None:
    """A re-run of ``publish-release`` alone still fetches PyPI's missing bytes."""
    for name in scene.ARTEFACTS:
        (fake.pypi / name).write_bytes(f"published {name}".encode())
        if name != scene.PYPI_ONLY:
            shutil.copyfile(fake.pypi / name, fake.github / name)
    (fake.github / scene.BUNDLE).write_bytes(b"bundle")

    cwd = scene.publish_release(fake)

    assert outputs(cwd / "output")["pending"] == "true", (
        "the release must still lack the PyPI-only name"
    )
    assert (fake.github / scene.PYPI_ONLY).read_bytes() == (
        f"published {scene.PYPI_ONLY}".encode()
    ), "the release must receive PyPI's bytes for the missing name"


def test_a_complete_rerun_uploads_nothing_even_though_it_staged_the_bundle(
    fake: FakeRelease,
) -> None:
    """A second run reaches a published release and leaves its assets alone.

    The run still builds and attests a bundle, so the staging step always
    offers one; with the release already public, the upload step must decline
    it. This is the acceptance criterion that a repeated tag uploads nothing.
    """
    for name in scene.ARTEFACTS:
        (fake.pypi / name).write_bytes(f"published {name}".encode())
        shutil.copyfile(fake.pypi / name, fake.github / name)
    (fake.github / scene.BUNDLE).write_bytes(b"bundle")
    before = scene.holdings(fake.github)

    cwd, env = scene.job_directory(fake, "publish-release")
    env.update(FAKE_RELEASE_DRAFT="false")
    for name in scene.PUBLISH_STEPS:
        scene.run_required("publish-release", name, cwd, env)
    assert not list((cwd / "github-upload").iterdir()), (
        "a published release has nothing lacking, the bundle included"
    )
    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )

    assert scene.holdings(fake.github) == before, (
        "the bundle name must not be added again"
    )
    uploads = [call for call in fake.calls("gh") if call[:2] == ["release", "upload"]]
    assert uploads == [], uploads


def test_the_upload_step_refuses_a_staged_bundle_for_a_published_release(
    fake: FakeRelease,
) -> None:
    """The guard, not only the staging step, keeps a published release unchanged.

    ``publish-release``'s staging step can only offer a bundle when the index
    it read still lacks it, and PyPI's CDN can serve such a stale index. The
    upload step must therefore decline on its own once the release is public.
    """
    cwd, env = scene.job_directory(fake, "publish-release")
    staged = cwd / "github-upload"
    staged.mkdir()
    (staged / scene.BUNDLE).write_bytes(b"bundle")
    before = scene.holdings(fake.github)
    # The draft check is what records the published state the upload reads.
    scene.run_required(
        "publish-release",
        scene.DRAFT_STEP,
        cwd,
        {**env, "FAKE_RELEASE_DRAFT": "false"},
    )

    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )

    assert scene.holdings(fake.github) == before, (
        "a staged bundle must not change a published release"
    )
    uploads = [call for call in fake.calls("gh") if call[:2] == ["release", "upload"]]
    assert uploads == [], uploads
