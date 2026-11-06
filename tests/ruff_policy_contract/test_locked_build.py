"""Behaviour: ``--locked`` refuses a stale lockfile and never rewrites it.

``test_provenance`` reads the Makefile and asserts that the ``build`` recipe
carries ``--locked``. That is a claim about the text of a command, and this
branch is the one that added the flag, so the claim deserves the behaviour
behind it: a matching lockfile must sync, a stale one must fail, and neither
must leave a rewritten lockfile behind.

The probe builds a throwaway project in a temporary directory rather than
touching this one. ``uv`` is asked for a resolution with no dependencies and
``--offline``, so the test needs no network and cannot perturb the repository's
own lock. What it exercises is uv's handling of the flag, not this project's
dependency graph, which is the part the contract is about.
"""

from __future__ import annotations

import shutil
import subprocess  # ruff: ignore[S404]  # Runs a pinned executable, no shell.
import sys
from pathlib import Path

import pytest

from .reading import RuffPolicyError

#: A project with nothing to resolve. ``--offline`` and an empty dependency
#: list keep the probe to one package, so it completes without a network and
#: cannot fail for a reason unrelated to the lockfile.
_PROJECT = """\
[project]
name = "lock-probe"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
"""

#: What ``--locked`` is meant to refuse: a requirement the lock does not
#: satisfy. Changing the version is the smallest edit that makes the existing
#: lock stale without touching a dependency.
_STALE_PROJECT = _PROJECT.replace('version = "0.1.0"', 'version = "0.2.0"')


def _uv() -> str:
    """Return the uv executable, or skip when the probe cannot run.

    Returns
    -------
    str
        The path to ``uv``, as the shell would resolve it.

    """
    executable = shutil.which("uv")
    if executable is None:
        pytest.skip("uv is not installed, so the locked-sync probe cannot run")
    return executable


def _uv_run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``uv`` against ``project`` with output captured.

    Parameters
    ----------
    project : Path
        The directory holding the throwaway ``pyproject.toml``.
    *args : str
        The uv arguments, in order.

    Returns
    -------
    subprocess.CompletedProcess[str]
        The finished run, with its streams decoded.

    """
    return subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
        [_uv(), *args],
        capture_output=True,
        check=False,
        cwd=project,
        text=True,
    )


def _locked_project(tmp_path: Path, pyproject: str) -> tuple[Path, str]:
    """Write ``pyproject`` to ``tmp_path`` and lock it.

    Parameters
    ----------
    tmp_path : Path
        Where to write the project.
    pyproject : str
        The ``pyproject.toml`` body.

    Returns
    -------
    tuple[Path, str]
        The project directory and the lockfile's text as ``uv lock`` wrote it.

    Raises
    ------
    RuffPolicyError
        If the throwaway project cannot be locked. Returning an unlocked
        directory would let both cases below pass without a lockfile to
        refuse, which is the vacuous result this test exists to avoid.

    """
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    completed = _uv_run(tmp_path, "lock", "--offline")
    lock = tmp_path / "uv.lock"
    if completed.returncode != 0 or not lock.is_file():
        message = (
            "could not lock the throwaway project, so nothing below would be "
            f"refusing anything: {completed.stderr}"
        )
        raise RuffPolicyError(message)
    return tmp_path, lock.read_text(encoding="utf-8")


class TestLockedSync:
    """A matching lock syncs; a stale one fails; neither rewrites the lock."""

    def test_a_matching_lockfile_syncs(self, tmp_path: Path) -> None:
        """The negative control: ``--locked`` must not refuse a clean lock.

        Without this row a ``--locked`` that rejected everything would satisfy
        the stale case below, and the test would be measuring refusal rather
        than the difference between the two lockfiles.
        """
        project, before = _locked_project(tmp_path, _PROJECT)
        completed = _uv_run(project, "sync", "--locked", "--offline")
        assert completed.returncode == 0, (
            "--locked refused a lockfile that matches the project, so the "
            "flag is rejecting more than staleness and the `make build` it "
            f"guards would fail on a clean tree; stderr was {completed.stderr}"
        )
        after = (project / "uv.lock").read_text(encoding="utf-8")
        assert after == before, (
            "a permitted `uv sync --locked` rewrote the lockfile, so the flag "
            "does not leave a clean tree clean"
        )

    def test_a_stale_lockfile_is_refused(self, tmp_path: Path) -> None:
        """The reported defect: a lock that no longer matches must fail."""
        project, _ = _locked_project(tmp_path, _PROJECT)
        (project / "pyproject.toml").write_text(_STALE_PROJECT, encoding="utf-8")
        completed = _uv_run(project, "sync", "--locked", "--offline")
        assert completed.returncode != 0, (
            "`uv sync --locked` succeeded against a lockfile the project no "
            "longer matches, so `make build` can install a resolution nobody "
            "reviewed"
        )
        assert "--locked" in completed.stderr, (
            "the sync failed but not because of `--locked`, so this case is "
            f"passing for the wrong reason; stderr was {completed.stderr!r}"
        )

    def test_a_refused_sync_does_not_update_the_lockfile(self, tmp_path: Path) -> None:
        """A refused build must fail loudly rather than quietly fix the lock."""
        project, _ = _locked_project(tmp_path, _PROJECT)
        (project / "pyproject.toml").write_text(_STALE_PROJECT, encoding="utf-8")
        stale = (project / "uv.lock").read_text(encoding="utf-8")
        _uv_run(project, "sync", "--locked", "--offline")
        assert (project / "uv.lock").read_text(encoding="utf-8") == stale, (
            "the refused sync rewrote the lockfile anyway, so the failure is "
            "reported after the unreviewed resolution has already been "
            "written and a second run would succeed"
        )


def test_the_probe_uses_this_projects_uv() -> None:
    """The probe must exercise the same uv the gate does, not a stray one."""
    completed = subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
        [_uv(), "--version"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, (
        f"`uv --version` failed, so the probe cannot stand in for the gate's "
        f"`make build`; stderr was {completed.stderr}"
    )
    assert "uv " in completed.stdout, (
        f"the resolved uv printed an unexpected version line: {completed.stdout!r}"
    )
    assert sys.version_info >= (3, 11), "the probe's requires-python is unmet"
