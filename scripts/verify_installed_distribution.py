#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Verify that an installed wheel exposes the hecate-enforce interface.

CI builds the wheel, installs it into a clean virtual environment outside the
checkout, and runs this script with the runner's Python. This module therefore
uses only the standard library: the interpreter running it is not the
environment under test, so nothing here can rely on the project's runtime or
development dependencies being importable.

The checks are deliberately interface-level. They confirm the installed
metadata names ``hecate-enforce``, that ``hecate`` imports, that both
documented command-line entry points answer ``--help``, and that ``hecate
check`` accepts a small valid policy. A malformed wheel that merely happens to
build fails here before it can be published.
"""

from __future__ import annotations

import argparse
import subprocess  # noqa: S404 - the checks are commands in the environment under test.
import sys
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_DISTRIBUTION = "hecate-enforce"
_IMPORT = "hecate"
_METADATA_CHECK = (
    "import importlib.metadata as metadata; "
    f"assert metadata.metadata({_DISTRIBUTION!r})['Name'] == {_DISTRIBUTION!r}"
)


class VerificationError(Exception):
    """The installed distribution does not expose the expected interface."""


def _run(command: list[str], *, cwd: Path) -> None:
    """Run one check, reporting the command and its output when it fails."""
    completed = subprocess.run(  # noqa: S603 - fixed commands, never a shell.
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        msg = (
            f"{' '.join(command)} failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
        raise VerificationError(msg)


def verify(venv: Path, policy: Path) -> None:
    """Check the metadata, import, and both command-line entry points."""
    python = venv / "bin" / "python"
    hecate = venv / "bin" / "hecate"
    for executable in (python, hecate):
        if not executable.is_file():
            msg = f"{executable} is missing from the virtual environment"
            raise VerificationError(msg)
    # `-I` keeps the checkout and any ambient PYTHONPATH out of the environment
    # under test, so an import can only succeed from the installed wheel.
    _run([str(python), "-I", "-c", _METADATA_CHECK], cwd=venv)
    _run([str(python), "-I", "-c", f"import {_IMPORT}"], cwd=venv)
    _run([str(python), "-I", "-m", _IMPORT, "--help"], cwd=venv)
    _run([str(hecate), "--help"], cwd=venv)
    _run([str(hecate), "check", "--config", str(policy)], cwd=venv)


def main(argv: cabc.Sequence[str] | None = None) -> int:
    """Run the installed-distribution checks; report failures as annotations."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify(args.venv, args.policy)
    except (VerificationError, OSError) as error:
        print(f"::error title=installed-distribution::{error}", file=sys.stderr)
        return 1
    print("The installed wheel exposes the hecate-enforce interface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
