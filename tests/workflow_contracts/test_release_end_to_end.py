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

import dataclasses as dc
import os
import pathlib as pth
import shutil
import subprocess  # noqa: S404 - the test runs the build the workflow runs.
import sys
import tarfile
import tomllib

import pytest

from . import release_scenario as scene
from .ci_workflows import ROOT
from .release_workflow import FakeRelease, run_version_check

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


@dc.dataclass(frozen=True, slots=True)
class _Build:
    """One build's ``release-dist`` artefact, and the tag that names it."""

    version: str
    tag: str
    dist: pth.Path
    expected: dict[str, bytes]


def _release_once(fake: FakeRelease, run: str, *, draft: bool, build: _Build) -> bool:
    """Run the workflow's jobs in dependency order for one tag push.

    ``build`` is the ``release-dist`` artefact the build job uploads and the
    bytes it holds, so a caller can supply a synthetic build or a real one.

    Returns whether ``publish-pypi`` told the workflow that artefacts remained,
    which is the condition its upload step reads.
    """
    check = fake.root / f"check-version-{run}"
    check.mkdir()
    completed, stated = run_version_check(check, build.version, build.version)
    assert completed.returncode == 0, completed.stderr
    assert stated["prerelease"] == "false", f"{build.version} is not a pre-release"

    # The build job uploads `release-dist`; every later job downloads it and
    # works from those bytes alone.
    snapshot = scene.snapshot_release(
        fake,
        create=True,
        staged=scene.Job(
            label=f"draft-release-{run}", dist_from=build.dist, tag=build.tag
        ),
    )
    assert scene.holdings(snapshot / "dist" / "publish") == build.expected, (
        "draft-release must receive the build job's artefacts unchanged"
    )

    remaining = scene.publish_pypi_from_snapshot(
        fake,
        snapshot,
        staged=scene.Job(
            label=f"publish-pypi-{run}", dist_from=build.dist, tag=build.tag
        ),
    )

    published = scene.publish_release(
        fake,
        scene.ReleaseRun(
            label=f"publish-release-{run}",
            draft=draft,
            publish=True,
            dist_from=build.dist,
            tag=build.tag,
        ),
    )
    assert scene.holdings(published / "dist" / "publish") == build.expected, (
        "publish-release must receive the build job's artefacts unchanged"
    )
    return remaining


def _synthetic_build(fake: FakeRelease, run: str) -> _Build:
    """Return a build the workflow never made, for one release run."""
    dist = scene.job_directory(fake, "build", scene.Job(label=f"build-{run}"))[0]
    return _Build(
        version=scene.TAG.removeprefix("v"),
        tag=scene.TAG,
        dist=dist / "dist",
        expected={name: scene.local(name) for name in scene.ARTEFACTS},
    )


def _synthetic_release_once(fake: FakeRelease, run: str, *, draft: bool) -> bool:
    """Drive one tag push against a synthetic build the workflow never made."""
    return _release_once(fake, run, draft=draft, build=_synthetic_build(fake, run))


def _declared_version() -> str:
    """Return the version ``pyproject.toml`` declares."""
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def _uv_build(
    destination: pth.Path,
    project: pth.Path = ROOT,
    env: dict[str, str] | None = None,
) -> pth.Path:
    """Build ``project`` with the workflow's own ``uv build`` command.

    ``project`` is this checkout unless a test needs a project shaped like the
    one a CI job builds, such as a copy carrying a virtual environment.
    ``env`` replaces the inherited environment where a test needs the build's
    own files to stay outside the project.
    """
    uv = shutil.which("uv")
    assert uv is not None, "the test suite runs under uv, so the build must find it"
    completed = subprocess.run(  # noqa: S603 - the resolved build command runs in the repository root.
        [uv, "build", "--out-dir", str(destination)],
        capture_output=True,
        check=False,
        cwd=project,
        env=env,
        text=True,
    )
    assert completed.returncode == 0, (
        "`uv build` must succeed for the release test to mean anything:\n"
        f"{completed.stderr}"
    )
    return destination


def _built_files(output: pth.Path) -> dict[str, bytes]:
    """Return the sdist and wheel ``uv build`` wrote, keyed by name.

    ``uv build`` also drops a ``.gitignore`` in its output directory; the
    workflow stages only the distributions, so this does too.
    """
    return {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.suffix in {".whl", ".gz"}
    }


def _release_dist(output: pth.Path, version: str, dist: pth.Path) -> pth.Path:
    """Shape one build's output as the ``release-dist`` artefact.

    The build job leaves the sdist and wheel under ``dist/publish`` and the
    attestation under ``dist/attestations``; this mirrors that layout from a
    real build, so every later job reads the files ``uv build`` wrote.
    """
    (dist / "publish").mkdir(parents=True)
    for name, content in _built_files(output).items():
        (dist / "publish" / name).write_bytes(content)
    (dist / "attestations").mkdir()
    bundle = f"hecate-enforce-v{version}.sigstore.json"
    (dist / "attestations" / bundle).write_bytes(b"bundle")
    return dist


def test_a_complete_release_publishes_and_a_rerun_uploads_nothing(
    fake: FakeRelease,
) -> None:
    """The first run publishes every name; the second changes no bytes."""
    for name in scene.ARTEFACTS:
        (fake.pypi / name).unlink(missing_ok=True)
        (fake.github / name).unlink(missing_ok=True)

    assert _synthetic_release_once(fake, "first", draft=True), (
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

    assert not _synthetic_release_once(fake, "rerun", draft=False), (
        "a rerun must tell the workflow that no artefact remains"
    )

    after = len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]])
    assert after == before, "a rerun of a published release must upload nothing"
    assert scene.holdings(fake.github) == published, (
        "a rerun must not change any asset's bytes"
    )
    assert scene.holdings(fake.pypi) == expected, "PyPI must be left untouched"


def test_a_conflicting_destination_keeps_the_release_a_draft(
    fake: FakeRelease,
) -> None:
    """A digest conflict stops publication, and a rerun cannot publish either.

    The digest check is what stands between the upload and a visible release,
    so this drives the sequence as GitHub does: every step up to the check
    runs, the check fails, and the publish step is never reached -- in this
    run or the next.
    """
    (fake.pypi / scene.BOTH).write_bytes(b"PyPI's bytes")
    (fake.github / scene.BOTH).write_bytes(b"the release's bytes")

    first = _synthetic_build(fake, "first")
    assert not scene.publish_after_check(
        fake, "first", draft=True, dist_from=first.dist
    ), "a digest conflict must stop the run before it publishes"
    assert scene.publication_edits(fake) == [], (
        "a failed check must leave the release a draft"
    )

    # A rerun rebuilds every name, but reconciliation never overwrites either
    # destination, so the two conflicting copies remain and the check fails
    # again.
    rerun = _synthetic_build(fake, "rerun")
    assert not scene.publish_after_check(
        fake, "rerun", draft=True, dist_from=rerun.dist
    ), "a rerun must not publish a release the check cannot pass"
    assert scene.publication_edits(fake) == [], (
        "a rerun must still leave the release a draft"
    )
    assert fake.pypi.joinpath(scene.BOTH).read_bytes() == b"PyPI's bytes", (
        "a failed check must not rewrite PyPI's bytes"
    )
    assert fake.github.joinpath(scene.BOTH).read_bytes() == b"the release's bytes", (
        "a failed check must not rewrite the release's bytes"
    )


@pytest.mark.timeout(300)
def test_a_real_build_reaches_both_destinations_and_a_rerun_changes_nothing(
    fake: FakeRelease, tmp_path: pth.Path
) -> None:
    """The bytes ``uv build`` writes are the bytes both destinations hold.

    The synthetic run above proves the workflow's paths carry *some* bytes.
    This one builds the project with the same ``uv build`` the workflow runs,
    so the names, checksums, and metadata the release reconciles are the ones
    the package actually has, and a second real build -- which need not be
    byte-identical -- must still leave both destinations untouched.
    """
    version = _declared_version()
    tag = f"v{version}"
    bundle = f"hecate-enforce-{tag}.sigstore.json"
    for name in (*scene.ARTEFACTS, scene.BUNDLE):
        (fake.pypi / name).unlink(missing_ok=True)
        (fake.github / name).unlink(missing_ok=True)

    first = _uv_build(tmp_path / "first-build")
    first_bytes = _built_files(first)
    assert len(first_bytes) == 2, (
        f"`uv build` must produce one sdist and one wheel, not {sorted(first_bytes)}"
    )

    assert _release_once(
        fake,
        "first",
        draft=True,
        build=_Build(
            version=version,
            tag=tag,
            dist=_release_dist(first, version, tmp_path / "first-dist"),
            expected=first_bytes,
        ),
    ), "a first release must tell the workflow to upload"

    assert scene.holdings(fake.pypi) == first_bytes, (
        "PyPI must hold exactly the bytes `uv build` produced"
    )
    assert scene.holdings(fake.github) == {**first_bytes, bundle: b"bundle"}, (
        "the release must ship the built bytes plus the bundle it attests"
    )

    uploads = len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]])
    second = _uv_build(tmp_path / "second-build")
    second_bytes = _built_files(second)

    assert not _release_once(
        fake,
        "rerun",
        draft=False,
        build=_Build(
            version=version,
            tag=tag,
            dist=_release_dist(second, version, tmp_path / "second-dist"),
            expected=second_bytes,
        ),
    ), "a rerun must tell the workflow that no artefact remains"

    assert len([c for c in fake.calls("gh") if c[:2] == ["release", "upload"]]) == (
        uploads
    ), "a rerun of a published release must upload nothing"
    assert scene.holdings(fake.pypi) == first_bytes, (
        "PyPI's immutable bytes must survive a rebuild"
    )
    assert scene.holdings(fake.github) == {**first_bytes, bundle: b"bundle"}, (
        "the release must keep the bytes it published, whatever the rebuild holds"
    )


@pytest.mark.timeout(120)
def test_the_sdist_never_carries_a_virtual_environment(tmp_path: pth.Path) -> None:
    """A checkout's venv must not reach the sdist, or the build cannot finish.

    CI creates ``.venv-coverage`` inside the checkout, and a venv's
    ``bin/python`` is an absolute symlink. ``uv build`` builds the sdist first
    and then unpacks it to build the wheel from it, and it refuses an archive
    holding such a link -- so a venv inside the sdist fails the build rather
    than merely enlarging it. Hatchling would otherwise include every file the
    VCS does not ignore, so the exclusion is build configuration rather than an
    ignore-file entry: the archive is the same whether or not git is present.
    """
    version = _declared_version()
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copyfile(ROOT / name, project / name)
    shutil.copytree(
        ROOT / "hecate",
        project / "hecate",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    interpreter = project / ".venv-coverage" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)

    # The Makefile exports a relative `UV_CACHE_DIR`, which `uv` would resolve
    # against this copy and then pack into the sdist, hiding the venv behind a
    # second excluded name. Point the cache outside the project so the venv is
    # the only thing the build could pick up.
    built = _uv_build(
        tmp_path / "dist",
        project,
        env={**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")},
    )

    assert sorted(_built_files(built)) == [
        f"hecate_enforce-{version}-py3-none-any.whl",
        f"hecate_enforce-{version}.tar.gz",
    ], "the copy must build exactly the distributions the release publishes"
    with tarfile.open(built / f"hecate_enforce-{version}.tar.gz") as archive:
        names = archive.getnames()
    assert not [name for name in names if "/.venv" in name], (
        f"the sdist must not carry the checkout's virtual environment: {names}"
    )
    assert any(name.endswith("/hecate/cli.py") for name in names), (
        "the exclusion must not have emptied the archive"
    )
    assert not [name for name in names if "/.uv-cache" in name], (
        "the build's own cache must stay outside the source distribution"
    )
