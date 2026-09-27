"""Unit tests for edges whose internal target cannot be resolved.

A ``from pkg.gone import helper`` where ``pkg.gone`` is missing is still an
edge, and it must be reported rather than skipped. These tests pin how many
diagnostics such an import yields and which of them survive, because the two
failure modes are opposite: reporting the target and the symbol separately
double-counts one broken import, while suppressing the symbol outright would
drop a dependency that genuinely resolves.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import ArchitecturePolicy, EdgeState, ModuleGroup

_STRICT_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application")),
)

_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain", "api")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application", "adapter")),
)


def _policy(
    *,
    groups: tuple[ModuleGroup, ...] = _GROUPS,
    strict: bool = False,
) -> ArchitecturePolicy:
    """Return a policy built from the fixtures' usual knobs."""
    return ArchitecturePolicy(groups=groups, strict=strict)


def _check(
    root: Path,
    files: dict[str, str],
    *,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Build a package, check it, and return the result."""
    package_root = root / "pkg"
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=policy if policy is not None else _policy(),
    )
    return check_architecture(config)


def test_unresolved_wildcard_target_records_one_edge_not_two(tmp_path: Path) -> None:
    """A wildcard over an unresolvable target reports that target exactly once.

    The statement's own module edge and the wildcard target are the same edge,
    so recording it in both places would double-count the diagnostic.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.gone import *\n",
        },
        policy=_policy(strict=True),
    )

    targeted = [
        diagnostic
        for diagnostic in result.coverage
        if diagnostic.imported == "pkg.gone"
    ]
    assert len(targeted) == 1, (
        f"expected exactly one diagnostic for the target, got {targeted!r}"
    )


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
        policy=_policy(strict=True),
    )

    assert not result.ok, f"expected strict failure, got {result!r}"
    assert any(
        diagnostic.state is EdgeState.UNRESOLVED for diagnostic in result.coverage
    ), f"expected unresolved state, got {result.coverage!r}"


def test_unreachable_symbol_edge_is_not_reported_twice(tmp_path: Path) -> None:
    """One broken ``from`` import yields one diagnostic, not two.

    ``from pkg.gone import helper`` produces a target edge and a symbol edge.
    With ``pkg.gone`` missing, the symbol cannot be reached either, so
    reporting both would count a single broken import twice and inflate the
    coverage output an adopter has to work through.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.gone import helper\n",
        },
        policy=_policy(strict=True),
    )

    unresolved = [
        diagnostic
        for diagnostic in result.coverage
        if diagnostic.state is EdgeState.UNRESOLVED
    ]
    assert [diagnostic.imported for diagnostic in unresolved] == ["pkg.gone"], (
        f"expected the target alone to be reported, got {result.coverage!r}"
    )


def test_symbol_that_resolves_under_missing_parent_is_still_reported(
    tmp_path: Path,
) -> None:
    """A resolvable symbol is a real edge even when its parent does not resolve.

    ``pkg.gone`` has no ``__init__``, so the parent names no module, yet
    ``gone/helper.py`` is a real file that the import genuinely reaches. The
    target and the symbol are then different facts, and both must be reported:
    suppressing the symbol edge here would drop a real dependency.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.gone import helper\n",
            "gone/helper.py": "",
        },
        policy=_policy(strict=True),
    )

    imported = {diagnostic.imported for diagnostic in result.coverage}
    assert "pkg.gone.helper" in imported, (
        f"a resolvable symbol must still be reported, got {result.coverage!r}"
    )
    assert "pkg.gone" in imported, (
        f"the unresolvable parent must still be reported, got {result.coverage!r}"
    )
