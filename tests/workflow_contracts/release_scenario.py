"""Shared staging for the release's end-to-end reconciliation tests.

``test_release_reconciliation.py`` and ``test_release_rerun.py`` both drive the
checked-in steps of ``draft-release``, ``publish-pypi``, and
``publish-release`` against the same ``gh`` and ``curl`` stand-ins. The
scenario they share lives here: one workspace per job, this run's artefacts and
bundle, and the destinations seeded with one name per reconciliation case.
"""

from __future__ import annotations

import re
import shutil
import typing as typ

import pytest

from .release_workflow import (
    FakeRelease,
    fake_release,
    link_scripts,
    outputs,
    run_bash,
    step,
    step_script,
)

if typ.TYPE_CHECKING:
    import pathlib as pth
    import subprocess

TAG = "v1.2.3"
#: The bundle is named after the tag, not the run, so a re-run meets the name
#: the release already holds and uploads nothing.
BUNDLE = f"hecate-enforce-{TAG}.sigstore.json"
#: One name per reconciliation case: PyPI only, GitHub only, neither, both.
PYPI_ONLY, GITHUB_ONLY, NEITHER, BOTH = (
    "hecate_enforce-1.2.3-py3-none-any.whl",
    "hecate_enforce-1.2.3-cp314-cp314-linux.whl",
    "hecate_enforce-1.2.3-cp314-cp314-macos.whl",
    "hecate_enforce-1.2.3.tar.gz",
)
ARTEFACTS = (PYPI_ONLY, GITHUB_ONLY, NEITHER, BOTH)
DRAFT_STEP = "Note whether the release is a draft"
PUBLISH_STEPS = (
    DRAFT_STEP,
    "Fetch the PyPI index",
    "List the release assets",
    "Stage the assets the release lacks",
    "Check the fetched PyPI bytes",
)


def local(name: str) -> bytes:
    """Return the bytes this run's build produced for ``name``."""
    return f"rebuilt {name}".encode()


def job_directory(fake: FakeRelease, job: str) -> tuple[pth.Path, dict[str, str]]:
    """Stage one job's workspace with this run's artefacts and bundle."""
    cwd = fake.root / job
    for name in ARTEFACTS:
        (cwd / "dist" / "publish").mkdir(parents=True, exist_ok=True)
        (cwd / "dist" / "publish" / name).write_bytes(local(name))
    (cwd / "dist" / "attestations").mkdir(parents=True)
    (cwd / "dist" / "attestations" / BUNDLE).write_bytes(b"bundle")
    link_scripts(cwd)
    return cwd, fake.env(GITHUB_REF_NAME=TAG, GITHUB_OUTPUT=str(cwd / "output"))


_STEP_OUTPUT = re.compile(r"\$\{\{\s*steps\.([\w-]+)\.outputs\.([\w-]+)\s*\}\}")


def _reference(template: str, step_id: str, name: str, stated: dict[str, str]) -> str:
    """Return the value a ``steps.<id>.outputs.<name>`` reference resolves to.

    The workflow writes a step's outputs under whichever key the script chose,
    which is usually but not always ``<id>-<name>``; the bare key is the other
    form in use.
    """
    for key in (f"{step_id}-{name}", name):
        if key in stated:
            return stated[key]
    msg = f"no output {step_id}.{name} was written by the preceding steps"
    raise AssertionError(msg)


def _substitute(value: str, stated: dict[str, str]) -> str:
    """Replace each ``steps.<id>.outputs.<name>`` reference with its value."""
    return _STEP_OUTPUT.sub(
        lambda match: _reference(value, match.group(1), match.group(2), stated),
        value,
    )


def run_step(
    job: str, name: str, cwd: pth.Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one step with its declared ``env`` resolved as GitHub Actions does.

    Resolving the declaration rather than restating it means the test exercises
    the workflow's real wiring, including any variable a step opts into.
    """
    stated = outputs(cwd / "output")
    declared = typ.cast("dict[str, str]", step(job, name).get("env") or {})
    resolved = {
        variable: _substitute(str(value), stated)
        for variable, value in declared.items()
    }
    return run_bash(step_script(job, name), cwd, {**env, **resolved})


def run_required(job: str, name: str, cwd: pth.Path, env: dict[str, str]) -> None:
    """Run one step and require it to succeed."""
    completed = run_step(job, name, cwd, env)
    assert completed.returncode == 0, (  # noqa: S101 - a test helper's contract.
        f"{job}/{name}: {completed.stderr}"
    )


def draft_and_publish_pypi(fake: FakeRelease) -> None:
    """Run the snapshot, the PyPI staging, and the modelled PyPI upload."""
    draft, env = job_directory(fake, "draft-release")
    run_required("draft-release", "Snapshot the release assets", draft, env)
    pypi, env = job_directory(fake, "publish-pypi")
    shutil.copytree(draft / "github-state", pypi / "github-state")
    run_required("publish-pypi", "Fetch the PyPI index", pypi, env)
    run_required("publish-pypi", "Skip artefacts already on PyPI", pypi, env)
    if outputs(pypi / "output")["remaining"] == "true":
        for staged in (pypi / "dist" / "publish").iterdir():
            assert not (fake.pypi / staged.name).exists(), (  # noqa: S101
                "PyPI never overwrites"
            )
            shutil.copyfile(staged, fake.pypi / staged.name)


def publish_release(fake: FakeRelease, *, verify: bool = True) -> pth.Path:
    """Run ``publish-release`` up to its digest check; return its workspace."""
    cwd, env = job_directory(fake, "publish-release")
    for name in PUBLISH_STEPS:
        run_required("publish-release", name, cwd, env)
    run_required("publish-release", "Upload the assets the release lacks", cwd, env)
    # The index is re-read after the upload, so the digest check sees PyPI's
    # state now rather than the copy fetched before anything was published.
    run_required("publish-release", "Re-fetch the PyPI index", cwd, env)
    if verify:
        run_required(
            "publish-release", "Check both destinations hold the same bytes", cwd, env
        )
    return cwd


def holdings(directory: pth.Path) -> dict[str, bytes]:
    """Return each file's bytes in one destination."""
    return {path.name: path.read_bytes() for path in directory.iterdir()}


@pytest.fixture
def fake(tmp_path: pth.Path) -> FakeRelease:
    """Return destinations seeded with one name per reconciliation case."""
    release = fake_release(tmp_path)
    (release.pypi / PYPI_ONLY).write_bytes(b"pypi")
    (release.github / GITHUB_ONLY).write_bytes(b"github")
    (release.pypi / BOTH).write_bytes(b"both")
    (release.github / BOTH).write_bytes(b"both")
    return release
