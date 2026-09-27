"""Unit tests for checker orchestration rules."""

from __future__ import annotations

import textwrap
from pathlib import Path

from hecate.checker import check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import ArchitecturePolicy, EdgeState, IgnoredImport, ModuleGroup

_SAMPLE_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain", "api")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application", "adapter")),
)

_STRICT_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application")),
)


def _build_package(root: Path, files: dict[str, str]) -> None:
    """Write a scratch package tree from relative paths to source text."""
    for relative_path, contents in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")


def _check(
    root: Path,
    files: dict[str, str],
    *,
    groups: tuple[ModuleGroup, ...] = _SAMPLE_GROUPS,
    strict: bool = False,
    ignores: tuple[IgnoredImport, ...] = (),
    include_external_packages: bool = False,
):
    """Build a package, check it, and return the result."""
    package_root = root / "pkg"
    _build_package(package_root, files)
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=ArchitecturePolicy(
            groups=groups,
            ignores=ignores,
            strict=strict,
            include_external_packages=include_external_packages,
        ),
    )
    return check_architecture(config)


def test_external_imports_are_skipped_when_disabled(tmp_path: Path) -> None:
    """External classified prefixes require explicit opt-in."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain.py": "import sqlalchemy\n",
        },
        groups=(
            ModuleGroup("domain", ("pkg",), ("domain",)),
            ModuleGroup("infrastructure", ("sqlalchemy",), ("infrastructure",)),
        ),
    )

    assert result.ok, f"expected external import to be skipped, got {result!r}"
    assert not result.coverage, (
        f"expected no coverage noise for a skipped external import, got {result!r}"
    )


def test_explicit_import_keeps_origin_when_all_omits_it(tmp_path: Path) -> None:
    """An explicitly imported re-export stays forbidden despite ``__all__ = []``."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "api/__init__.py": "from ..adapters.database import Database\n__all__ = []\n",
            "api/routes.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.api import Database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
            "domain/__init__.py": "",
        },
    )

    imported = {violation.imported for violation in result.violations}
    assert not result.ok, f"expected a violation, got {result!r}"
    assert "pkg.adapters.database.Database" in imported, (
        f"expected the re-export origin to be flagged, got {imported!r}"
    )


def test_wildcard_consumer_expands_to_symbol_origins(tmp_path: Path) -> None:
    """A wildcard consumer inherits the origins its export set provides."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "api/__init__.py": "from ..adapters.database import Database\n__all__ = ['Database']\n",
            "api/routes.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.api import *\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
            "domain/__init__.py": "",
        },
    )

    imported = {violation.imported for violation in result.violations}
    assert "pkg.adapters.database.Database" in imported, (
        f"wildcard consumer hid a forbidden dependency, got {imported!r}"
    )


def test_wildcard_over_empty_all_binds_no_symbols(tmp_path: Path) -> None:
    """A wildcard over ``__all__ = []`` contributes only the module edge."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "api/__init__.py": "from ..adapters.database import Database\n__all__ = []\n",
            "api/routes.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.api import *\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
            "domain/__init__.py": "",
        },
    )

    consumer_imports = {
        violation.imported
        for violation in result.violations
        if violation.importer == "pkg.application.service"
    }
    assert "pkg.adapters.database.Database" not in consumer_imports, (
        f"an empty __all__ must not export symbols to a wildcard, "
        f"got {consumer_imports!r}"
    )


def test_unclassified_internal_subtree_is_reported_not_skipped(tmp_path: Path) -> None:
    """A subtree matching no group is surfaced as unclassified coverage."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.newthing import helper\n",
            "newthing/__init__.py": "",
            "newthing/helper.py": "",
        },
    )

    assert result.ok, f"non-strict mode should not fail, got {result!r}"
    states = {diagnostic.state for diagnostic in result.coverage}
    assert EdgeState.UNCLASSIFIED in states, (
        f"expected an unclassified coverage entry, got {result.coverage!r}"
    )


def test_strict_mode_fails_on_unclassified_internal_edge(tmp_path: Path) -> None:
    """Strict mode turns an unclassified internal edge into a failure."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.newthing import helper\n",
            "newthing/__init__.py": "",
            "newthing/helper.py": "",
        },
        strict=True,
    )

    assert not result.ok, f"strict mode must fail an unclassified edge, got {result!r}"
    assert result.coverage_failures, (
        f"expected coverage failures in strict mode, got {result!r}"
    )


def test_strict_mode_reports_unresolved_internal_distinctly(tmp_path: Path) -> None:
    """An internal symbol no module binds is unresolved, not permitted."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.domain import missing_symbol\n",
        },
        strict=True,
    )

    assert not result.ok, f"strict mode must fail an unresolved edge, got {result!r}"
    states = {diagnostic.state for diagnostic in result.coverage}
    assert EdgeState.UNRESOLVED in states, (
        f"expected an unresolved coverage entry, got {result.coverage!r}"
    )


def test_unresolved_internal_can_be_downgraded_by_configuration(
    tmp_path: Path,
) -> None:
    """The unresolved-internal severity is configurable as the issue requires."""
    from hecate.policy import Severity

    package_root = tmp_path / "pkg"
    _build_package(
        package_root,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.domain import missing_symbol\n",
        },
    )
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=ArchitecturePolicy(
            groups=_STRICT_GROUPS,
            strict=True,
            unresolved_internal_severity=Severity.WARNING,
        ),
    )

    result = check_architecture(config)

    assert result.ok, f"a warning severity must not fail the check, got {result!r}"
    assert result.coverage, f"expected the edge to still be reported, got {result!r}"


def test_documented_ignore_still_exempts_and_stays_distinguishable(
    tmp_path: Path,
) -> None:
    """A configured ignore exempts an edge and is reported as such."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.adapters.database import Database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
        },
        groups=_STRICT_GROUPS,
        strict=True,
        ignores=(
            IgnoredImport(
                importer="pkg.application",
                imported="pkg.adapters",
                reason="Legacy wiring pending migration.",
            ),
        ),
    )

    assert result.ok, f"a documented ignore must suppress the violation, got {result!r}"
    assert result.ignored, f"expected the exemption to be reported, got {result!r}"
    assert all(
        entry.state is not EdgeState.FORBIDDEN for entry in result.coverage
    ), "an exempted edge must be distinguishable from an unclassified one"


def test_internal_import_of_unknown_module_is_unresolved(tmp_path: Path) -> None:
    """An internal target no module provides is unresolved, not external."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.gone import helper\n",
        },
        strict=True,
    )

    assert not result.ok, f"expected strict failure, got {result!r}"
    assert any(
        diagnostic.state is EdgeState.UNRESOLVED for diagnostic in result.coverage
    ), f"expected unresolved state, got {result.coverage!r}"
