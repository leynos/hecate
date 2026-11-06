#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Verify that the built archives and installed wheel expose hecate-enforce.

CI builds the sdist and wheel, installs the wheel into a clean virtual
environment outside the checkout, and runs this script with the runner's
Python. This module therefore uses only the standard library: the interpreter
running it is not the environment under test, so nothing here can rely on the
project's runtime or development dependencies being importable.

The checks are deliberately interface-level. They confirm both archives name
``hecate-enforce`` and declare the version ``pyproject.toml`` states, that the
installed metadata names ``hecate-enforce``, that ``hecate`` imports, that both
documented command-line entry points answer ``--help``, and that ``hecate
check`` accepts a small valid policy. A malformed archive that merely happens
to build fails here before it can be published.
"""

from __future__ import annotations

import argparse
import email.parser
import subprocess  # noqa: S404 - the checks are commands in the environment under test.
import sys
import tarfile
import tomllib
import typing as typ
import zipfile
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


def _declared_version(pyproject: Path) -> str:
    """Return the ``[project]`` version ``pyproject.toml`` declares."""
    with pyproject.open("rb") as handle:
        document = tomllib.load(handle)
    return typ.cast("str", document["project"]["version"])


def _single(directory: Path, pattern: str, label: str) -> Path:
    """Return the one ``directory`` entry matching ``pattern``, or fail."""
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        msg = f"expected exactly one {label} in {directory}, found {len(matches)}"
        raise VerificationError(msg)
    return matches[0]


def _check_metadata(label: str, text: str, version: str) -> None:
    """Fail unless one archive's core metadata names the distribution and version."""
    headers = email.parser.Parser().parsestr(text, headersonly=True)
    name, found = headers["Name"], headers["Version"]
    if name != _DISTRIBUTION:
        msg = f"{label} names {name!r}, not {_DISTRIBUTION!r}"
        raise VerificationError(msg)
    if found != version:
        msg = f"{label} declares version {found!r}, not pyproject.toml's {version!r}"
        raise VerificationError(msg)


def _wheel_metadata(wheel: Path) -> str:
    """Return the ``METADATA`` text of one wheel."""
    with zipfile.ZipFile(wheel) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ),
            None,
        )
        if member is None:
            msg = f"{wheel.name} has no METADATA"
            raise VerificationError(msg)
        return archive.read(member).decode("utf-8")


def _sdist_metadata(sdist: Path) -> str:
    """Return the ``PKG-INFO`` text of one source distribution."""
    with tarfile.open(sdist) as archive:
        member = next(
            (item for item in archive.getmembers() if item.name.endswith("/PKG-INFO")),
            None,
        )
        if member is None:
            msg = f"{sdist.name} has no PKG-INFO"
            raise VerificationError(msg)
        extracted = archive.extractfile(member)
        if extracted is None:
            msg = f"{sdist.name} has an unreadable PKG-INFO"
            raise VerificationError(msg)
        return extracted.read().decode("utf-8")


def verify_archives(dist: Path, pyproject: Path) -> None:
    """Check the sdist's ``PKG-INFO`` and the wheel's ``METADATA`` agree.

    Both archives are published under the version the tag names, so a build
    that misnames the distribution or stamps a different version would reach
    PyPI under a name and version nobody asked for. Checking the archives
    themselves catches that before the upload, not after it.
    """
    version = _declared_version(pyproject)
    wheel = _single(dist, "*.whl", "wheel")
    sdist = _single(dist, "*.tar.gz", "source distribution")
    _check_metadata(f"{wheel.name} METADATA", _wheel_metadata(wheel), version)
    _check_metadata(f"{sdist.name} PKG-INFO", _sdist_metadata(sdist), version)


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
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--pyproject", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify_archives(args.dist, args.pyproject)
        verify(args.venv, args.policy)
    except (VerificationError, OSError) as error:
        print(f"::error title=installed-distribution::{error}", file=sys.stderr)
        return 1
    print("The archives and installed wheel expose the hecate-enforce interface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
