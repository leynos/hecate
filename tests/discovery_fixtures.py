"""Shared helper for tests that analyse namespaces.

``analyse_namespaces`` consumes already-walked package roots rather than
walking them itself, so every test that builds ``PackageRoot`` values in a
temporary tree needs the same one-line conversion first. It lives here instead
of in each test module because the conversion is mechanical and says nothing
about what any one test asserts.
"""

from __future__ import annotations

import typing as typ

from hecate.imports import discover_modules

if typ.TYPE_CHECKING:
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
