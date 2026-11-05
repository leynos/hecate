"""Behaviour of the release workflow's version check, collection, and PyPI steps.

The steps run their checked-in scripts in a scratch directory, with ``curl``
replaced by a stand-in serving scripted index responses, so the contract is
what the release actually executes: the tag must equal the declared version,
exactly one sdist travels with the wheels, the index lookup retries transient
failures and counts them, and files already on PyPI are skipped by name, with
nothing left meaning no upload at all.
"""

from __future__ import annotations

import json
import sys
import tomllib
import typing as typ

import pytest

from .ci_workflows import ROOT
from .release_workflow import (
    FakeRelease,
    fake_release,
    link_scripts,
    outputs,
    run_bash,
    run_version_check,
    step_script,
)

if typ.TYPE_CHECKING:
    import pathlib as pth
    import subprocess

_COLLECT_STEP = ("attest", "Collect release artefacts")
_INDEX_STEP = ("publish-pypi", "Fetch the PyPI index")
_SKIP_STEP = ("publish-pypi", "Skip artefacts already on PyPI")
_ARTEFACTS = ("hecate_enforce-1.2.3-py3-none-any.whl", "hecate_enforce-1.2.3.tar.gz")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


def _touch(directory: pth.Path, *names: str) -> None:
    """Create artefact files named ``names`` under ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(name.encode())


@pytest.mark.parametrize(
    ("version", "expected_prerelease"),
    [
        ("0.2.0-beta1", "true"),
        ("0.2.0b1", "true"),
        ("1.0.0-rc.2", "true"),
        ("1.0.0a3", "true"),
        ("1.0.0.post1.dev2", "true"),
        ("1.2.3", "false"),
        ("1.2.3.post1", "false"),
        ("1.2.3+rc1", "false"),
        ("10.20.30", "false"),
    ],
)
def test_a_matching_tag_passes_and_reports_its_prerelease_status(
    tmp_path: pth.Path, version: str, expected_prerelease: str
) -> None:
    """The tag-derived version must equal the declared one, in either spelling."""
    completed, written = run_version_check(tmp_path, version, version)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert written == {"prerelease": expected_prerelease}, (
        f"{version} must be reported as prerelease={expected_prerelease}"
    )


@pytest.mark.parametrize(
    ("declared", "tag_version"),
    [("1.2.2", "1.2.3"), ("0.2.0-beta1", "0.2.0b1"), ("0.2.0-beta1", "0.2.0")],
    ids=["older-manifest", "respelled-prerelease", "dropped-prerelease"],
)
def test_a_mismatched_tag_fails_before_anything_is_published(
    tmp_path: pth.Path, declared: str, tag_version: str
) -> None:
    """A tag naming another version stops the release with an annotation."""
    completed, written = run_version_check(tmp_path, declared, tag_version)

    assert completed.returncode != 0, "a mismatched tag must fail the release"
    assert "::error file=pyproject.toml,title=Tag/pyproject.toml mismatch::" in (
        completed.stdout
    ), "a mismatch must be annotated against the manifest"
    assert not written, "a failed check must not report a prerelease status"


def test_the_distribution_is_the_name_the_release_publishes() -> None:
    """The declared name is the one the index lookup and the release URL use."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")

    assert pyproject["project"]["name"] == "hecate-enforce", (
        "the distribution must be published as hecate-enforce"
    )
    assert "https://pypi.org/simple/hecate-enforce/" in workflow, (
        "the index lookup must name the published distribution"
    )
    assert "https://pypi.org/project/hecate-enforce/" in workflow, (
        "the release notes must link the published distribution"
    )


def test_collection_gathers_the_sdist_with_every_wheel(tmp_path: pth.Path) -> None:
    """Wheels from every artefact directory and the one sdist are collected."""
    _touch(tmp_path / "dist" / "wheels-pure", *_ARTEFACTS)

    completed = run_bash(step_script(*_COLLECT_STEP), tmp_path)

    assert completed.returncode == 0, completed.stderr
    collected = sorted(path.name for path in (tmp_path / "dist" / "publish").iterdir())
    assert collected == list(_ARTEFACTS), "every wheel and the sdist must be staged"


@pytest.mark.parametrize(
    "sdists",
    [(), ("hecate_enforce-1.2.3.tar.gz", "hecate_enforce-1.2.2.tar.gz")],
    ids=["no-sdist", "two-sdists"],
)
def test_collection_fails_without_exactly_one_sdist(
    tmp_path: pth.Path, sdists: tuple[str, ...]
) -> None:
    """A release that lost its sdist, or gained a second, fails before upload."""
    _touch(tmp_path / "dist" / "wheels-pure", _ARTEFACTS[0], *sdists)

    completed = run_bash(step_script(*_COLLECT_STEP), tmp_path)

    assert completed.returncode != 0, "the release needs exactly one sdist"
    assert "Expected exactly one source distribution." in completed.stderr, (
        "the failure must name the missing or duplicated sdist"
    )


def test_collection_fails_without_a_wheel(tmp_path: pth.Path) -> None:
    """A release that lost every wheel fails before it can be attested."""
    _touch(tmp_path / "dist" / "wheels-pure", _ARTEFACTS[1])

    completed = run_bash(step_script(*_COLLECT_STEP), tmp_path)

    assert completed.returncode != 0, "the release needs at least one wheel"
    assert "Expected at least one wheel." in completed.stderr, (
        "the failure must name the missing wheel"
    )


def test_collection_refuses_an_unexpected_file(tmp_path: pth.Path) -> None:
    """An artefact holding anything else would be attested without review."""
    _touch(tmp_path / "dist" / "wheels-pure", *_ARTEFACTS)
    (tmp_path / "dist" / "wheels-pure" / "notes.txt").write_text("hi", "utf-8")

    completed = run_bash(step_script(*_COLLECT_STEP), tmp_path)

    assert completed.returncode != 0, "an unexpected file must fail the release"
    assert "Unexpected files in the release artefact:" in completed.stderr, (
        "the failure must name the unexpected file"
    )


def _fetch_and_skip(
    tmp_path: pth.Path, statuses: str, published: tuple[str, ...] = ()
) -> tuple[FakeRelease, subprocess.CompletedProcess[str], dict[str, str]]:
    """Run the index fetch, then the skip step if the fetch succeeded."""
    fake = fake_release(tmp_path)
    link_scripts(tmp_path)
    _touch(tmp_path / "dist" / "publish", *_ARTEFACTS)
    _touch(fake.pypi, *published)
    (tmp_path / "github-state" / "files").mkdir(parents=True)
    (tmp_path / "github-state" / "assets.json").write_text('{"assets": []}', "utf-8")
    env = fake.env(FAKE_CURL_STATUSES=statuses)
    completed = run_bash(step_script(*_INDEX_STEP), tmp_path, env)
    if completed.returncode == 0:
        completed = run_bash(step_script(*_SKIP_STEP), tmp_path, env)
    return fake, completed, outputs(tmp_path / "github-output")


def _remaining(tmp_path: pth.Path) -> list[str]:
    """Return the artefact names left for the PyPI upload."""
    return sorted(path.name for path in (tmp_path / "dist" / "publish").iterdir())


@pytest.mark.parametrize(
    ("published", "remaining", "has_remaining"),
    [
        (_ARTEFACTS[1:], [_ARTEFACTS[0]], "true"),
        (_ARTEFACTS, [], "false"),
    ],
    ids=["uploads-remaining", "nothing-left"],
)
def test_artefacts_already_on_pypi_are_skipped_by_name(
    tmp_path: pth.Path,
    published: tuple[str, ...],
    remaining: list[str],
    has_remaining: str,
) -> None:
    """Only unpublished names remain, and the step says whether any do."""
    _, completed, written = _fetch_and_skip(tmp_path, "200", published)

    assert completed.returncode == 0, completed.stderr
    assert _remaining(tmp_path) == remaining, "published names must be dropped"
    assert f"::notice::Skipping {_ARTEFACTS[1]}: already on PyPI" in completed.stdout, (
        "a published name must be reported as skipped"
    )
    assert written == {"attempts": "1", "status": "200", "remaining": has_remaining}, (
        "the step must report whether anything remains to upload"
    )


def test_a_project_absent_from_pypi_reads_as_an_empty_index(
    tmp_path: pth.Path,
) -> None:
    """A 404 is a first release: nothing is skipped and every file uploads."""
    _, completed, written = _fetch_and_skip(tmp_path, "404")

    assert completed.returncode == 0, completed.stderr
    index = json.loads((tmp_path / "pypi-index.json").read_text(encoding="utf-8"))
    assert index == {"files": []}, "a 404 must be read as an empty index"
    assert _remaining(tmp_path) == list(_ARTEFACTS), (
        "a first release must upload every artefact"
    )
    assert written == {"attempts": "1", "status": "404", "remaining": "true"}, (
        "a 404 must leave every artefact to upload"
    )


def test_a_transient_failure_is_retried_and_counted(tmp_path: pth.Path) -> None:
    """A 503 then a 429 then a 200 succeeds on the third attempt."""
    fake, completed, written = _fetch_and_skip(tmp_path, "503,429,200")

    assert completed.returncode == 0, completed.stderr
    assert written["attempts"] == "3", "the retry count must be reported"
    assert written["status"] == "200", "the retry must end on the successful status"
    assert len(fake.calls("curl")) == 3, "each attempt must make exactly one request"


@pytest.mark.parametrize(
    ("statuses", "attempts"),
    [("500", "6"), ("000", "6"), ("403", "1")],
    ids=["server-error", "network-error", "client-error"],
)
def test_a_failed_index_lookup_stops_the_upload(
    tmp_path: pth.Path, statuses: str, attempts: str
) -> None:
    """A persistent 5xx or network error, or any other 4xx, fails the job."""
    fake, completed, written = _fetch_and_skip(tmp_path, statuses)

    assert completed.returncode != 0, f"HTTP {statuses} must fail the lookup"
    assert f"PyPI simple index returned HTTP {statuses}." in completed.stderr, (
        "the failure must name the status that stopped the lookup"
    )
    assert written == {"attempts": attempts, "status": statuses}, (
        "the step must report the attempts and the final status"
    )
    assert len(fake.calls("curl")) == int(attempts), "the loop must stay bounded"
    assert _remaining(tmp_path) == list(_ARTEFACTS), "nothing may be skipped"
