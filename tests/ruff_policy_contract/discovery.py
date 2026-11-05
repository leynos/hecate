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
    import collections.abc as cabc
    from pathlib import Path


def checked_python_files() -> tuple[Path, ...]:
    """Return the tracked Python files the lint gate runs over.

    Read from Git rather than by walking the tree: an untracked scratch file
    is not part of the gate, and the gate's own targets are directories, so
    what it checks is exactly what Git tracks under them.

    Stubs count. Ruff discovers ``.pyi`` files when it checks a directory and
    applies a configuration to them, so a directory holding only a stub is
    still governed by whatever configuration sits there.

    Returns
    -------
    tuple[Path, ...]
        The tracked ``.py`` and ``.pyi`` files, as absolute paths in Git's
        listing order.

    Raises
    ------
    RuffPolicyError
        If Git cannot list the files. A reader that returned ``()`` instead
        would leave the caller with no directories to inspect, so the
        nested-configuration contract would pass without having looked.

    """
    try:
        # A literal pathspec list, so S603 does not apply. Git comes from PATH
        # in CI just as it does here, so the partial-path warning is intended.
        # Stubs count too: Ruff checks .pyi files, so a directory holding only
        # one is still governed by any configuration in it.
        completed = subprocess.run(
            # ruff: ignore[S607]  # Git comes from PATH in CI, as it does here.
            ["git", "ls-files", "-z", "--", "*.py", "*.pyi"],
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

    Parameters
    ----------
    project_file : Path
        The ``pyproject.toml`` to inspect. It is assumed to exist already; a
        missing file is reported as unreadable rather than as declaring
        nothing.

    Returns
    -------
    bool
        ``True`` when the file has a ``tool.ruff`` table, whatever its
        contents. A table that sets nothing still re-roots Ruff's resolution
        and so still counts.

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

    Parameters
    ----------
    directory : Path
        The directory to inspect. Neither its ancestors nor its descendants
        are searched, so a caller wanting every level has to pass each one.

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


def directories_between(root: Path, files: cabc.Iterable[Path]) -> tuple[Path, ...]:
    """Return every directory strictly inside ``root`` that contains a file.

    Ruff resolves a file's settings by walking *upwards* from the file, not by
    looking at the file's own directory alone. A ``ruff.toml`` two levels above
    a module re-roots that module just as surely as one beside it, so the
    intermediate directories have to be named. Taking the ancestors of the
    files themselves finds them without walking the tree, and a directory that
    holds no file is left out because it governs nothing.

    Parameters
    ----------
    root : Path
        The directory whose own configuration is not in question. It and
        anything outside it are excluded.
    files : cabc.Iterable[Path]
        Paths to the files whose governing directories are wanted.

    Returns
    -------
    tuple[Path, ...]
        The distinct directories, sorted. ``root`` itself is never included:
        its configuration is the one the inventory records.

    """
    directories = {
        parent for file in files for parent in file.parents if root in parent.parents
    }
    return tuple(sorted(directories))
