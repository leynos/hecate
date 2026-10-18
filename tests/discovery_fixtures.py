"""Shared helper for tests that analyse namespaces.

``analyse_namespaces`` consumes already-walked package roots rather than
walking them itself, so every test that builds ``PackageRoot`` values in a
temporary tree needs the same one-line conversion first. It lives here instead
of in each test module because the conversion is mechanical and says nothing
about what any one test asserts.

The module also owns the fixture for an unlistable directory, because tests of
discovery and of the CLI must provoke the same failure the same way.
"""

from __future__ import annotations

import typing as typ

import pytest

from hecate.imports import discover_modules

if typ.TYPE_CHECKING:
    from pathlib import Path

    from hecate.config import PackageRoot
    from hecate.imports import Discovery


def discover_package_roots(
    packages: tuple[PackageRoot, ...],
) -> tuple[Discovery, ...]:
    """Return the walked module list for each package root."""
    return tuple(
        discover_modules(package_root.root, package_root.name)
        for package_root in packages
    )


def make_directory_unlistable(directory: Path) -> None:
    """Deny all access to ``directory``, or skip when that cannot work.

    The failure path these tests exist for only appears if listing really is
    refused. A privileged test process ignores the permission bits, so without
    this check the test would pass while exercising a successful walk.

    Parameters
    ----------
    directory : Path
        Directory whose permissions should prevent listing.
    """
    directory.chmod(0)
    try:
        list(directory.iterdir())
    except OSError:
        return
    pytest.skip("process can list a chmod-0 directory; cannot simulate failure")
