"""Synthetic distributions shaped like the ones the release publishes.

``test_ci_wheel_build.py`` runs CI's archive and installation checks against a
wheel and an sdist it writes itself, so a check can be exercised without a real
build. This module holds those builders: the fixtures are large enough to
obscure the tests that use them, and both the archive tests and the
installed-metadata test share them.
"""

from __future__ import annotations

import base64
import dataclasses as dc
import hashlib
import io
import tarfile
import typing as typ
import zipfile
from itertools import starmap

if typ.TYPE_CHECKING:
    from pathlib import Path

#: The wheel's command shim: ``check`` exits with the status the caller chose.
CLI = """\
import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    return {check_exit} if "check" in args else 0
"""


def record(name: str, data: bytes) -> str:
    """Return one ``RECORD`` line with the wheel's URL-safe digest."""
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
    return f"{name},sha256={digest.rstrip(b'=').decode()},{len(data)}"


def vendored_metadata(name: str) -> bytes:
    """Return a nested distribution's core metadata, as a vendored copy would be."""
    return f"Metadata-Version: 2.1\nName: {name}\nVersion: 9.9.9\n".encode()


@dc.dataclass(frozen=True, slots=True)
class WheelSpec:
    """What a synthetic wheel should contain.

    ``vendored`` adds a nested ``.dist-info`` for another distribution, written
    first so archive order alone would find it before the wheel's own metadata.
    """

    name: str = "hecate-enforce"
    include_package: bool = True
    check_exit: int = 0
    vendored: str | None = None


DEFAULT_WHEEL = WheelSpec()


def write_wheel(directory: Path, spec: WheelSpec = DEFAULT_WHEEL) -> Path:
    """Write a small wheel that mimics the interface the release must expose."""
    directory.mkdir(parents=True, exist_ok=True)
    normalized = spec.name.replace("-", "_")
    dist_info = f"{normalized}-0.1.0.dist-info"
    files: dict[str, bytes] = {}
    if spec.vendored is not None:
        nested = f"hecate/_vendor/{spec.vendored.replace('-', '_')}-9.9.9.dist-info"
        files[f"{nested}/METADATA"] = vendored_metadata(spec.vendored)
    files |= {
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {spec.name}\nVersion: 0.1.0\n".encode()
        ),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: ci-wheel-build-test\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
        f"{dist_info}/entry_points.txt": (
            b"[console_scripts]\nhecate = hecate.cli:main\n"
        ),
    }
    if spec.include_package:
        files.update({
            "hecate/__init__.py": b"",
            "hecate/__main__.py": (
                b"from hecate.cli import main\nraise SystemExit(main())\n"
            ),
            "hecate/cli.py": CLI.format(check_exit=spec.check_exit).encode(),
        })
    records = list(starmap(record, files.items()))
    records.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(records) + "\n").encode()

    wheel = directory / f"{normalized}-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return wheel


def write_sdist(
    directory: Path,
    *,
    name: str = "hecate-enforce",
    version: str = "0.1.0",
    vendored: str | None = None,
) -> Path:
    """Write a small source distribution whose ``PKG-INFO`` mirrors the wheel.

    ``version`` alone may disagree with the wheel, so a test can show that the
    sdist's metadata is judged on its own. ``vendored`` adds a nested
    ``PKG-INFO`` for another distribution, written first so that archive order
    alone would find it before the sdist's own.
    """
    directory.mkdir(parents=True, exist_ok=True)
    normalized = name.replace("-", "_")
    payload = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    sdist = directory / f"{normalized}-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        if vendored is not None:
            nested = f"{normalized}-{version}/hecate/_vendor/{vendored}/PKG-INFO"
            add_member(archive, nested, vendored_metadata(vendored))
        add_member(archive, f"{normalized}-{version}/PKG-INFO", payload)
    return sdist


def add_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    """Add one file to an open tar archive."""
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))
