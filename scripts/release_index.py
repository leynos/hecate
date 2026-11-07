"""Read the two destinations a release reconciles, and hash what it ships.

PyPI answers with a PEP 691 JSON simple index and the GitHub Release with
``gh release view --json assets``. Both listings are reduced here to the one
fact reconciliation needs: which filenames each destination holds, and the
SHA-256 digest of each. The decisions built on those facts live in
``scripts/release_assets.py``.

This module runs inside the job that holds the PyPI publishing token, so it
resolves no third-party code and every network call stays in the workflow's
``curl`` and ``gh`` steps.
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import json
import re
import typing as typ
import urllib.parse

if typ.TYPE_CHECKING:
    from pathlib import Path

#: The PEP 691 JSON simple index; relative file URLs resolve against it.
INDEX_URL = "https://pypi.org/simple/hecate-enforce/"

#: Artefact names this module will stage. Wheel and sdist names never need
#: more, and the bound keeps a name safe as a path and as a TSV field.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_DIGEST_PREFIX = "sha256:"


class ReleaseAssetError(Exception):
    """A release asset is missing, unsafe, or holds unexpected bytes."""


@dc.dataclass(frozen=True, slots=True)
class PypiFile:
    """One file the PyPI index lists."""

    sha256: str
    url: str


def read_pypi_index(path: Path) -> dict[str, PypiFile]:
    """Map each filename in a PEP 691 JSON index to its digest and URL.

    Parameters
    ----------
    path : Path
        A saved Simple index response. Each entry under ``files`` must carry
        ``filename``, ``hashes.sha256``, and ``url``; a missing key is a
        malformed index and raises ``KeyError``.

    Returns
    -------
    dict[str, PypiFile]
        The SHA-256 hex digest and absolute download URL per filename.

    """
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["filename"]: PypiFile(
            sha256=entry["hashes"]["sha256"].lower(),
            url=urllib.parse.urljoin(INDEX_URL, entry["url"]),
        )
        for entry in document.get("files", [])
    }


def read_github_assets(path: Path) -> dict[str, str | None]:
    """Map each asset in ``gh release view --json assets`` to its digest.

    Parameters
    ----------
    path : Path
        A saved ``gh release view --json assets`` response. Each entry under
        ``assets`` must carry ``name``; ``digest`` is optional.

    Returns
    -------
    dict[str, str | None]
        The SHA-256 hex digest per asset name, or ``None`` when GitHub reports
        no ``sha256:`` digest for that asset.

    """
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        asset["name"]: _digest_hex(asset.get("digest"))
        for asset in document.get("assets", [])
    }


def _digest_hex(digest: object) -> str | None:
    """Return the hex of a ``sha256:`` digest; ``None`` for any other form."""
    if isinstance(digest, str) and digest.startswith(_DIGEST_PREFIX):
        return digest.removeprefix(_DIGEST_PREFIX).lower()
    return None


def sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of one file's bytes.

    Parameters
    ----------
    path : Path
        The file to hash.

    Returns
    -------
    str
        The lowercase hexadecimal digest.

    """
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def local_names(directory: Path) -> list[str]:
    """List the artefact names in ``directory``, refusing any unsafe name.

    Parameters
    ----------
    directory : Path
        The directory holding this run's staged artefacts.

    Returns
    -------
    list[str]
        The file names, sorted.

    Raises
    ------
    ReleaseAssetError
        If any name is not a safe path component and TSV field.

    """
    names = sorted(path.name for path in directory.iterdir())
    unsafe = [name for name in names if not _SAFE_NAME.fullmatch(name)]
    if unsafe:
        msg = f"refusing unsafe artefact names: {unsafe}"
        raise ReleaseAssetError(msg)
    return names


def check_digest(path: Path, expected: str | None) -> None:
    """Raise unless ``path`` holds bytes with the ``expected`` digest.

    Parameters
    ----------
    path : Path
        The file to hash.
    expected : str | None
        The SHA-256 hex digest the file must match. ``None`` always fails,
        because a destination that reports no digest cannot be verified.

    Raises
    ------
    ReleaseAssetError
        If ``expected`` is ``None`` or differs from the file's digest.

    """
    actual = sha256_of(path)
    if expected is None or actual != expected:
        msg = f"{path.name} has sha256 {actual}, expected {expected}"
        raise ReleaseAssetError(msg)
