"""End-to-end behaviour of the release's asset reconciliation across its jobs.

Each test runs the checked-in steps of ``draft-release``, ``publish-pypi``, and
``publish-release`` in order, against ``gh`` and ``curl`` stand-ins whose
directories hold the GitHub Release's assets and PyPI's files. The one step
that cannot run here, pypa's upload action, is modelled as copying the staged
files to PyPI without overwriting, which is what ``skip-existing`` promises.
The assertions are about bytes: every name ends up identical on both sides,
taken from PyPI first, then GitHub, then this run, and nothing is replaced.

The re-run cases, where both destinations already hold every name, live in
``test_release_rerun.py``.
"""

from __future__ import annotations

import json
import sys

import pytest

from . import release_scenario as scene
from .release_workflow import FakeRelease, run_bash, step_script

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


def test_every_name_converges_on_its_canonical_bytes(fake: FakeRelease) -> None:
    """PyPI's bytes win, then GitHub's, then this run's, on both sides.

    This run's bundle is withheld: the run rebuilt ``PYPI_ONLY`` and
    ``GITHUB_ONLY``, so its attestation describes bytes the release does not
    ship. Attaching it would claim provenance for a different build.
    """
    scene.draft_and_publish_pypi(fake)
    scene.publish_release(fake)

    expected = {
        scene.PYPI_ONLY: b"pypi",
        scene.GITHUB_ONLY: b"github",
        scene.NEITHER: scene.local(scene.NEITHER),
        scene.BOTH: b"both",
    }
    assert scene.holdings(fake.pypi) == expected, "PyPI must hold the canonical bytes"
    assert scene.holdings(fake.github) == expected, (
        "the GitHub Release must hold the canonical bytes"
    )


def test_each_destination_is_sent_only_what_it_lacks(fake: FakeRelease) -> None:
    """GitHub is sent the PyPI-only and new names, nothing else."""
    scene.draft_and_publish_pypi(fake)
    scene.publish_release(fake)

    uploads = [call for call in fake.calls("gh") if call[:2] == ["release", "upload"]]
    assert len(uploads) == 1, uploads
    sent = sorted(path.rsplit("/", 1)[-1] for path in uploads[0][3:])
    assert sent == sorted((scene.PYPI_ONLY, scene.NEITHER))
    assert not any("--clobber" in call for call in fake.calls("gh"))


def test_the_bundle_is_attached_when_every_artefact_is_this_runs_build(
    fake: FakeRelease,
) -> None:
    """A first release ships the attested bytes, so its bundle is truthful."""
    for name in scene.ARTEFACTS:
        (fake.pypi / name).unlink(missing_ok=True)
        (fake.github / name).unlink(missing_ok=True)

    scene.draft_and_publish_pypi(fake)
    scene.publish_release(fake)

    assert (fake.github / scene.BUNDLE).read_bytes() == b"bundle", (
        "the bundle attests exactly the bytes both destinations now hold"
    )


def test_the_bundle_is_withheld_when_the_published_bytes_are_not_this_build(
    fake: FakeRelease,
) -> None:
    """An attestation must never describe bytes the release does not ship.

    A re-run rebuilds every artefact, and PyPI's immutable files stay
    canonical. The run's bundle attests the rebuild, so attaching it would put
    a provenance claim on the release that its own assets contradict. The
    attestation still reaches the repository's attestation store.
    """
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    for name in scene.PUBLISH_STEPS:
        scene.run_required("publish-release", name, cwd, env)

    assert list((cwd / "github-upload").iterdir()), "artefacts are staged"
    assert not (cwd / "github-upload" / scene.BUNDLE).exists(), (
        "the run's bundle must not ride along with bytes it did not build"
    )

    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )
    assert scene.BUNDLE not in scene.holdings(fake.github)


def test_the_check_fails_when_the_destinations_disagree(fake: FakeRelease) -> None:
    """Differing bytes under one name stop the release before it is visible."""
    (fake.github / scene.BOTH).write_bytes(b"clobbered by an earlier workflow")
    scene.draft_and_publish_pypi(fake)
    cwd = scene.publish_release(fake, verify=False)

    completed = run_bash(
        step_script("publish-release", "Check both destinations hold the same bytes"),
        cwd,
        fake.env(GITHUB_REF_NAME=scene.TAG, GITHUB_OUTPUT=str(cwd / "output")),
    )

    assert completed.returncode != 0, "a digest mismatch must fail the release"
    assert f"{scene.BOTH} differs" in completed.stderr
    assert (fake.github / scene.BOTH).read_bytes() == (
        b"clobbered by an earlier workflow"
    )


def test_bytes_that_do_not_match_the_index_are_never_uploaded(
    fake: FakeRelease,
) -> None:
    """A PyPI download whose digest differs from the index stops the upload."""
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    for name in scene.PUBLISH_STEPS[:3]:
        scene.run_required("publish-release", name, cwd, env)
    (fake.pypi / scene.PYPI_ONLY).write_bytes(b"tampered in transit")
    scene.run_required("publish-release", scene.PUBLISH_STEPS[3], cwd, env)

    completed = run_bash(
        step_script("publish-release", scene.PUBLISH_STEPS[4]), cwd, env
    )

    assert completed.returncode != 0, "a download must match PyPI's digest"
    assert scene.PYPI_ONLY in completed.stderr
    assert scene.PYPI_ONLY not in scene.holdings(fake.github)


def test_the_re_fetch_polls_past_a_cached_index(fake: FakeRelease) -> None:
    """A CDN cache that still predates the upload must not fail the release.

    PyPI serves its Simple index through a cache, so the first response after
    ``publish-pypi`` uploads a file can omit that file even though it has been
    published. The re-fetch therefore keeps asking, for a bounded number of
    attempts, until every name this run staged is listed; otherwise a
    successful release would stay a draft until the cache expired.
    """
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    for name in scene.PUBLISH_STEPS:
        scene.run_required("publish-release", name, cwd, env)
    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )
    just_published = ",".join((scene.PYPI_ONLY, scene.NEITHER))
    # Index readings so far: one in `publish-pypi`, one at the start of this
    # job. The next response is the stale cache, the one after it is current.
    env = {
        **env,
        "FAKE_CURL_STALE_AFTER": "2",
        "FAKE_CURL_STALE_CALLS": "1",
        "FAKE_CURL_STALE_NAMES": just_published,
    }
    before = len(fake.calls("curl"))

    refetch = scene.run_step("publish-release", "Re-fetch the PyPI index", cwd, env)
    assert refetch.returncode == 0, refetch.stderr
    scene.run_required(
        "publish-release", "Check both destinations hold the same bytes", cwd, env
    )

    listed = json.loads((cwd / "pypi-index.json").read_text(encoding="utf-8"))
    assert {entry["filename"] for entry in listed["files"]} == set(scene.ARTEFACTS), (
        "the re-fetch must end on a response that shows the upload"
    )
    index_url = "https://pypi.org/simple/hecate-enforce/"
    indexes = [call for call in fake.calls("curl")[before:] if call[-1] == index_url]
    assert len(indexes) == 2, "a stale response, then the one that shows the upload"
    assert "::error" not in refetch.stderr, (
        "a cache that is merely behind must not paint an error annotation"
    )


def test_the_re_fetch_stays_bounded_when_the_index_never_catches_up(
    fake: FakeRelease,
) -> None:
    """A cache that never shows the upload fails the step, not the job forever."""
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    for name in scene.PUBLISH_STEPS:
        scene.run_required("publish-release", name, cwd, env)
    scene.run_required(
        "publish-release", "Upload the assets the release lacks", cwd, env
    )
    env = {
        **env,
        "FAKE_CURL_STALE_AFTER": "1",
        "FAKE_CURL_STALE_CALLS": "99",
        "FAKE_CURL_STALE_NAMES": ",".join(scene.ARTEFACTS),
    }
    before = len(fake.calls("curl"))

    completed = scene.run_step("publish-release", "Re-fetch the PyPI index", cwd, env)

    assert completed.returncode != 0, "a permanently stale index must fail"
    assert "still does not list" in completed.stderr
    assert "::error" in completed.stderr, (
        "the final gate must annotate, unlike the retried attempts"
    )
    assert len(fake.calls("curl")) - before <= 6, "the poll must stay bounded"


def test_the_index_is_read_again_after_the_upload(fake: FakeRelease) -> None:
    """The digest check reads PyPI's state after the upload, not before it.

    PyPI serves the Simple index through a CDN cache, so the copy fetched at
    the start of ``publish-release`` can still omit a file ``publish-pypi``
    has just published. The re-fetch replaces that copy before the check
    compares the two destinations.
    """
    scene.draft_and_publish_pypi(fake)
    cwd, env = scene.job_directory(fake, "publish-release")
    stale = json.dumps({"name": "hecate-enforce", "files": []})
    (cwd / "pypi-index.json").write_text(stale, encoding="utf-8")

    scene.run_required("publish-release", "Re-fetch the PyPI index", cwd, env)

    listed = json.loads((cwd / "pypi-index.json").read_text(encoding="utf-8"))
    assert {entry["filename"] for entry in listed["files"]} == set(scene.ARTEFACTS), (
        "the re-fetch must replace a pre-upload copy of the index"
    )


def test_pypi_downloads_retry_and_are_bounded(fake: FakeRelease) -> None:
    """Every PyPI file download keeps the retry and timeout flags."""
    scene.draft_and_publish_pypi(fake)
    scene.publish_release(fake)

    downloads = [call for call in fake.calls("curl") if "--fail" in call]
    assert downloads, "the PyPI-only name must be fetched from PyPI"
    for call in downloads:
        joined = " ".join(call)
        for flag in ("--retry 5", "--retry-all-errors", "--connect-timeout 10"):
            assert flag in joined, f"a PyPI download must pass {flag}"
