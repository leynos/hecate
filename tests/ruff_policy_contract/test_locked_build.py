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

Two levels are measured, because a transcription is not the thing transcribed.
The ``uv sync`` cases state what the flag does; ``TestTheBuildTarget`` runs the
repository's own ``build`` recipe against the same throwaway project, so the
gates that would follow a future edit to that recipe are not left reading its
text.
"""

from __future__ import annotations

import shutil
import subprocess  # ruff: ignore[S404]  # Runs a pinned executable, no shell.
from pathlib import Path

import pytest

from .reading import REPO_ROOT, RuffPolicyError

#: The recipe ``TestTheBuildTarget`` drives. It is read, not rewritten: the
#: throwaway project supplies only the ``pyproject.toml`` and lockfile.
MAKEFILE = REPO_ROOT / "Makefile"

#: A project with nothing to resolve. ``--offline`` and an empty dependency
#: list keep the probe to one package, so it completes without a network and
#: cannot fail for a reason unrelated to the lockfile. The empty ``dev`` group
#: is what lets the build recipe's own ``--group dev`` resolve: without it uv
#: refuses the group, and the target case would fail for a reason that has
#: nothing to do with the lockfile.
_PROJECT = """\
[project]
name = "lock-probe"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = []
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
        """The reported defect: a lock that no longer matches must fail.

        The control is the same stale project synced without the flag, not a
        phrase in the refusal's stderr. A wording check would tie this case to
        uv's message and would still pass if the sync had failed for some other
        reason, whereas a plain sync that succeeds proves the staleness is the
        only difference between the two runs.
        """
        project, before = _locked_project(tmp_path, _PROJECT)
        (project / "pyproject.toml").write_text(_STALE_PROJECT, encoding="utf-8")

        refused = _uv_run(project, "sync", "--locked", "--offline")
        assert refused.returncode != 0, (
            "`uv sync --locked` succeeded against a lockfile the project no "
            "longer matches, so `make build` can install a resolution nobody "
            "reviewed"
        )

        allowed = _uv_run(project, "sync", "--offline")
        assert allowed.returncode == 0, (
            "the same stale project syncs without `--locked`, so the refusal "
            "above is about the flag; this control failing means the fixture "
            f"is broken rather than the lockfile: {allowed.stderr}"
        )
        assert (project / "uv.lock").read_text(encoding="utf-8") != before, (
            "an unlocked sync neither failed nor updated the lockfile, so it "
            "cannot be distinguished from the refused run and proves nothing "
            "about which one the flag refused"
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


class TestTheBuildTarget:
    """The repository's own ``build`` recipe, driven over the throwaway project.

    The cases above state what ``--locked`` does when it is passed. That is one
    step short of the question this module exists for: does the gate's recipe
    still pass it? ``test_provenance`` reads the recipe's text, and a text
    assertion cannot say the flag reached uv. Running the recipe through
    ``make`` — with the throwaway directory as its working directory and the
    repository's Makefile as its input — answers both at once, and would fail
    if the flag were dropped, renamed or shadowed by a later variable.
    """

    def _make(self, project: Path, *goals: str) -> subprocess.CompletedProcess[str]:
        """Run ``make`` in ``project`` against this repository's Makefile.

        Parameters
        ----------
        project : Path
            The throwaway project, used as make's working directory so the
            recipe's relative paths and prerequisites resolve there.
        *goals : str
            The make goals to run.

        Returns
        -------
        subprocess.CompletedProcess[str]
            The finished run, with its streams decoded.

        """
        # The recipe defaults the variable to `command -v uv` already; naming
        # the resolved path keeps the probe on the same binary this module
        # measured, rather than on whatever a caller's environment shadows it
        # with.
        argv = [
            "make",
            "-C",
            str(project),
            "-f",
            str(MAKEFILE),
            *goals,
            f"UV={_uv()}",
        ]
        return subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
            argv,
            capture_output=True,
            check=False,
            text=True,
        )

    def test_the_build_target_syncs_a_matching_lockfile(self, tmp_path: Path) -> None:
        """The negative control: the recipe must not refuse a clean lock."""
        project, before = _locked_project(tmp_path, _PROJECT)
        completed = self._make(project, "build")
        assert completed.returncode == 0, (
            "`make build` failed against a lockfile that matches the project, "
            "so the recipe is refusing more than staleness; stderr was "
            f"{completed.stderr}"
        )
        assert (project / "uv.lock").read_text(encoding="utf-8") == before, (
            "`make build` rewrote the lockfile it had just validated, so the "
            "gate does not leave a clean tree clean"
        )

    def test_the_build_target_refuses_a_stale_lockfile(self, tmp_path: Path) -> None:
        """The defect the flag was added for, measured through the recipe."""
        project, before = _locked_project(tmp_path, _PROJECT)
        (project / "pyproject.toml").write_text(_STALE_PROJECT, encoding="utf-8")
        completed = self._make(project, "build")
        assert completed.returncode != 0, (
            "`make build` succeeded against a lockfile the project no longer "
            "matches, so the gate can install a resolution nobody reviewed"
        )
        assert (project / "uv.lock").read_text(encoding="utf-8") == before, (
            "the refused `make build` rewrote the lockfile anyway, so the "
            "failure is reported after the unreviewed resolution has already "
            "been written"
        )


def test_the_probe_uses_the_uv_on_path() -> None:
    """The probe runs the uv a caller would get, and records which one.

    The version line is the whole assertion. ``make build`` resolves ``uv``
    through ``command -v``, and :func:`_uv` resolves it the same way, so the two
    agree by construction; what a reader of a failure needs is evidence that
    the binary was present and answered, which is what this prints when it does
    not.
    """
    completed = subprocess.run(  # ruff: ignore[S603]  # Literal argv, no shell.
        [_uv(), "--version"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, (
        "`uv --version` failed, so every probe above would skip or fail for a "
        f"reason unrelated to the lockfile; stderr was {completed.stderr}"
    )
    assert "uv " in completed.stdout, (
        f"the PATH-resolved uv printed an unexpected version line: {completed.stdout!r}"
    )
