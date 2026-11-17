"""Behaviour of the step that downloads PyPI's bytes into the release.

``publish-release``'s fetch loop is the release's only download: ``curl``
copies each file the GitHub Release lacks and PyPI already holds. The record
that loop leaves is how an operator learns which response family stopped a
run, so these tests execute the checked-in step against the fake tools and
assert on the standard error and exit status it really produces.

The cases are the ones a release can meet: every download succeeds, a later
download fails after an earlier one succeeded, and there is nothing to fetch
at all.
"""

from __future__ import annotations

import hashlib
import json
import typing as typ

import pytest

from .release_fake_tools import FILES_URL
from .release_workflow import (
    FakeRelease,
    fake_release,
    link_scripts,
    run_bash,
    step_script,
)

if typ.TYPE_CHECKING:
    import pathlib as pth
    import subprocess

_STEP = ("publish-release", "Stage the assets the release lacks")
#: Sorted, the wheel precedes the sdist, so a test can fail the second read.
_WHEEL, _SDIST = (
    "hecate_enforce-1.2.3-py3-none-any.whl",
    "hecate_enforce-1.2.3.tar.gz",
)


def _bytes(name: str) -> bytes:
    """Return this run's build of ``name``."""
    return f"built {name}".encode()


def _workspace(
    tmp_path: pth.Path, *names: str, listed: tuple[str, ...] | None = None
) -> tuple[FakeRelease, pth.Path]:
    """Stage the step's inputs with ``names`` on PyPI unless ``listed`` says otherwise.

    The release holds nothing, so every listed name is one the step must
    download. ``listed`` defaults to ``names``; an empty tuple models an index
    that lists none of this run's artefacts.
    """
    fake = fake_release(tmp_path)
    cwd = tmp_path / "publish-release"
    publish = cwd / "dist" / "publish"
    publish.mkdir(parents=True)
    for name in names:
        (publish / name).write_bytes(_bytes(name))
    index = [
        {
            "filename": name,
            "url": f"{FILES_URL}{name}",
            "hashes": {"sha256": hashlib.sha256(_bytes(name)).hexdigest()},
        }
        for name in (names if listed is None else listed)
    ]
    (cwd / "dist" / "attestations").mkdir(parents=True)
    (cwd / "pypi-index.json").write_text(json.dumps({"files": index}), "utf-8")
    (cwd / "release-assets.json").write_text(
        json.dumps({"assets": [], "isDraft": True}), "utf-8"
    )
    link_scripts(cwd)
    return fake, cwd


def _run(fake: FakeRelease, cwd: pth.Path) -> subprocess.CompletedProcess[str]:
    """Run the staging step with the run's correlation and a job summary."""
    return run_bash(
        step_script(*_STEP),
        cwd,
        fake.env(
            GITHUB_JOB="publish-release",
            GITHUB_RUN_ID="4711",
            GITHUB_RUN_ATTEMPT="2",
            GITHUB_STEP_SUMMARY=str(cwd / "summary.md"),
        ),
    )


def test_every_download_succeeds_and_is_recorded_as_2xx(tmp_path: pth.Path) -> None:
    """Two downloads that both answer 200 leave the step green."""
    fake, cwd = _workspace(tmp_path, _WHEEL, _SDIST)
    for name in (_WHEEL, _SDIST):
        (fake.pypi / name).write_bytes(_bytes(name))

    completed = _run(fake, cwd)

    assert completed.returncode == 0, completed.stderr
    assert (
        "release-event job=publish-release step=fetch-pypi outcome=ok "
        "status_class=2xx elapsed_s="
    ) in completed.stderr, "a successful fetch must record ok and the class it saw"
    assert (cwd / "github-upload" / _SDIST).read_bytes() == _bytes(_SDIST), (
        "the download must land in the directory the upload step reads"
    )


def test_a_failed_download_reports_its_own_class_not_the_earlier_2xx(
    tmp_path: pth.Path,
) -> None:
    """A 404 after a 200 is recorded as 4xx and fails the step."""
    fake, cwd = _workspace(tmp_path, _WHEEL, _SDIST)
    (fake.pypi / _WHEEL).write_bytes(_bytes(_WHEEL))

    completed = _run(fake, cwd)

    assert completed.returncode != 0, "a failed download must fail the step"
    assert "step=fetch-pypi outcome=failed status_class=4xx" in completed.stderr, (
        "the record must carry the class of the response that failed, not the "
        "2xx an earlier download received"
    )


def test_nothing_to_fetch_is_recorded_as_no_response(tmp_path: pth.Path) -> None:
    """An empty fetch list records no status class and still succeeds."""
    fake, cwd = _workspace(tmp_path, _WHEEL, listed=())

    completed = _run(fake, cwd)

    assert completed.returncode == 0, completed.stderr
    assert not (cwd / "pypi-fetch.tsv").read_text(encoding="utf-8"), (
        "this case is only meaningful when the step has nothing to download"
    )
    assert (
        "release-event job=publish-release step=fetch-pypi outcome=ok "
        "status_class=none elapsed_s="
    ) in completed.stderr, "no response at all must be recorded as none"


@pytest.mark.parametrize("name", [_WHEEL, _SDIST])
def test_the_staged_file_is_the_one_the_index_lists(
    tmp_path: pth.Path, name: str
) -> None:
    """One listed artefact is one download, named exactly as PyPI names it."""
    fake, cwd = _workspace(tmp_path, _WHEEL, _SDIST, listed=(name,))
    (fake.pypi / name).write_bytes(_bytes(name))

    completed = _run(fake, cwd)

    assert completed.returncode == 0, completed.stderr
    assert (cwd / "pypi-fetch.tsv").read_text(encoding="utf-8").splitlines() == [
        f"{name}\t{FILES_URL}{name}"
    ], "the step must download the name the index listed, from its own URL"
