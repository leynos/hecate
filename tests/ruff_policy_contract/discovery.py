"""Find the files the lint gate runs over, and the configuration it applies.

Ruff does not read one configuration per repository. For each file it walks
upwards and stops at the nearest directory holding a ``ruff.toml``,
``.ruff.toml``, or a ``pyproject.toml`` with a ``[tool.ruff]`` table. The
inventory this package commits is a single row, which is only honest while no
such file sits between the repository root and a source file: one in a
subdirectory would re-root the resolution for everything beneath it and make
the recorded row describe a policy those files do not use.

That makes the two questions here one question. "Which files does the gate
check" and "does any of them resolve against a nearer configuration" are
answered by the same pair of readers, so they live together rather than beside
the readers for the rule selection itself.
"""

from __future__ import annotations

import subprocess  # ruff: ignore[S404]  # Runs git, never user input.
import tomllib
import typing as typ

from .reading import REPO_ROOT, RuffPolicyError

if typ.TYPE_CHECKING:
    from pathlib import Path


def checked_python_files() -> tuple[Path, ...]:
    """Return the tracked Python files the lint gate runs over.

    Read from Git rather than by walking the tree: an untracked scratch file
    is not part of the gate, and the gate's own targets are directories, so
    what it checks is exactly what Git tracks under them.

    Raises
    ------
    RuffPolicyError
        If Git cannot list the files, since a reader that returned ``()``
        would let every per-file assertion below pass vacuously.

    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],  # ruff: ignore[S607]  # PATH, as in CI.
            capture_output=True,
            check=True,
            cwd=REPO_ROOT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        message = f"cannot list the tracked Python files: {error}"
        raise RuffPolicyError(message) from error
    return tuple(REPO_ROOT / name for name in completed.stdout.split("\0") if name)


def declares_ruff_settings(project_file: Path) -> bool:
    """Report whether a ``pyproject.toml`` carries any ``[tool.ruff]`` table.

    Raises
    ------
    RuffPolicyError
        If the file cannot be parsed. Ruff itself rejects such a file rather
        than falling back to a parent configuration, so treating an unreadable
        file as "configures nothing" would clear a directory Ruff refuses.

    """
    try:
        with project_file.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        message = f"cannot read {project_file}: {error}"
        raise RuffPolicyError(message) from error
    tool = document.get("tool")
    return isinstance(tool, dict) and "ruff" in tool


def ruff_configuration_candidates(directory: Path) -> tuple[Path, ...]:
    """Return the files in ``directory`` that Ruff would take as its config.

    Ruff resolves a file's settings from the nearest ancestor directory that
    holds a ``ruff.toml``, ``.ruff.toml`` or a ``pyproject.toml`` with a
    ``[tool.ruff]`` table, so any such file re-roots the resolution for
    everything beneath it. The search is non-recursive by design: the caller
    names the directories it cares about.

    Returns
    -------
    tuple[Path, ...]
        The candidates, in the precedence order Ruff documents. More than one
        is itself a finding, so the caller decides what to do about it.

    """
    standalone = tuple(
        directory / name
        for name in (".ruff.toml", "ruff.toml")
        if (directory / name).is_file()
    )
    project = directory / "pyproject.toml"
    nested = (project,) if project.is_file() and declares_ruff_settings(project) else ()
    return standalone + nested
