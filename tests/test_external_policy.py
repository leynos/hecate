"""Unit tests for the external-dependency policy boundary.

`include_external_packages` decides whether third-party prefixes may be
classified at all. It deliberately does *not* assert that every external import
was classified: a project enables the option to bring a claimed library such as
`sqlalchemy` under policy, not to declare that its whole dependency tree is
architecturally reviewed. These tests pin both halves of that rule, since the
error of over-reporting is as damaging as the error of under-reporting.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import ArchitecturePolicy, ModuleGroup

#: ``pkg`` itself is classified, and the policy additionally claims one
#: external prefix so the boundary under test is the claim, not the option.
_GROUPS = (
    ModuleGroup("domain", ("pkg",), ("domain",)),
    ModuleGroup("infrastructure", ("sqlalchemy",), ("infrastructure",)),
)


def _check(
    root: Path,
    files: dict[str, str],
    *,
    strict: bool,
    include_external_packages: bool,
) -> ArchitectureCheckResult:
    """Build a package, check it, and return the result."""
    package_root = root / "pkg"
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=ArchitecturePolicy(
            groups=_GROUPS,
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
        strict=False,
        include_external_packages=False,
    )

    assert result.ok, f"expected external import to be skipped, got {result!r}"
    assert not result.coverage, (
        f"expected no coverage noise for a skipped external import, got {result!r}"
    )


def test_unclaimed_external_import_does_not_fail_strict_mode(tmp_path: Path) -> None:
    """Strict mode must not fail every dependency no group claims.

    Opting into external packages widens what *can* be classified. It does not
    assert that every third-party import was classified, so an unclaimed
    external edge is skipped rather than reported. Otherwise ``import json``
    alone would fail a strict check.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain.py": "import json\nfrom collections.abc import Sequence\n",
        },
        strict=True,
        include_external_packages=True,
    )

    assert result.ok, (
        f"an unclaimed external import must not fail strict mode, got {result!r}"
    )
    assert not result.coverage, (
        f"expected no coverage noise for an unclaimed external import, got {result!r}"
    )


def test_claimed_external_import_is_still_enforced(tmp_path: Path) -> None:
    """A group that claims an external prefix remains a real boundary.

    Skipping unclaimed external edges must not weaken the case the option
    exists for, so this pins the other half of the rule.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain.py": "import sqlalchemy\n",
        },
        strict=True,
        include_external_packages=True,
    )

    imported = {violation.imported for violation in result.violations}
    assert not result.ok, (
        f"expected a claimed external import to be enforced, got {result!r}"
    )
    assert "sqlalchemy" in imported, (
        f"expected the external boundary to be flagged, got {imported!r}"
    )
