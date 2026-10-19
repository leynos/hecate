"""Unit tests for warning-level dependency directions.

Warning targets are policy declarations of edges that stay permitted but must
remain visible. The tests here pin the classifier's precedence, the way
warnings accumulate, and the configurations that must be rejected rather than
silently tolerated.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import ArchitecturePolicy, IgnoredImport, ModuleGroup

#: The barrel shapes the re-export test needs; both spell the same forbidden
#: origin, and differ only in whether ``__all__`` advertises it.
_REEXPORT_HIDDEN_FROM_WILDCARDS = (
    "from ..adapters.database import Database\n__all__ = []\n"
)

#: ``application`` warns ``adapter``, so the one edge between them is reported
#: without failing.
_WARN_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup(
        "application",
        ("pkg.application",),
        ("application", "domain"),
        ("adapter",),
    ),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
)

#: A package where ``application`` imports ``adapters``, the edge the warning
#: groups above tolerate.
_WARNED_EDGE_FILES = {
    "__init__.py": "",
    "domain/__init__.py": "",
    "application/__init__.py": "",
    "application/service.py": "from pkg.adapters.database import Database\n",
    "adapters/__init__.py": "",
    "adapters/database.py": "class Database: ...\n",
}


def _build_package(root: Path, files: dict[str, str]) -> None:
    """Write a scratch package tree from relative paths to source text."""
    for relative_path, contents in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")


def _policy(
    *,
    groups: tuple[ModuleGroup, ...] = _WARN_GROUPS,
    ignores: tuple[IgnoredImport, ...] = (),
) -> ArchitecturePolicy:
    """Return a non-strict policy built from the fixtures' usual knobs."""
    return ArchitecturePolicy(groups=groups, ignores=ignores, strict=False)


def _check(
    root: Path,
    files: dict[str, str],
    *,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Build a package, check it, and return the result."""
    package_root = root / "pkg"
    _build_package(package_root, files)
    config = HecateConfig(
        packages=(PackageRoot("pkg", package_root),),
        policy=policy if policy is not None else _policy(),
    )
    return check_architecture(config)


def _warned_edge_result(
    root: Path,
    *,
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Check the shared warned-edge package against a supplied policy."""
    return _check(root, _WARNED_EDGE_FILES, policy=policy)


def test_warning_target_reports_without_failing(tmp_path: Path) -> None:
    """A warned edge is reported, but does not fail the check by default."""
    result = _warned_edge_result(tmp_path, policy=_policy())

    assert result.ok, f"a warned edge must not fail the check, got {result!r}"
    assert not result.violations, (
        f"a warned edge must not be a violation, got {result.violations!r}"
    )
    assert not result.coverage, (
        f"a warned edge is classified, so it must not be coverage: {result.coverage!r}"
    )
    # A ``from X import Y`` statement contributes both the module edge and the
    # symbol edge, exactly as it does on the violation path.
    assert {warning.imported for warning in result.warnings} == {
        "pkg.adapters.database",
        "pkg.adapters.database.Database",
    }, f"expected both expanded edges to be warned, got {result.warnings!r}"
    for warning in result.warnings:
        assert warning.importer == "pkg.application.service", (
            f"expected the consumer as importer, got {warning.importer!r}"
        )
        assert (warning.importer_group, warning.imported_group) == (
            "application",
            "adapter",
        ), f"expected both groups on the warning, got {warning!r}"


def test_warning_identities_are_sorted_and_deduplicated(tmp_path: Path) -> None:
    """Warnings are de-duplicated and ordered by their identity.

    Importing one name twice on a single line yields two edges with the same
    identity: the target module, the named symbol, and that same named symbol
    again. Accumulating by identity must collapse the pair, so the exact list
    below fails if either edge is appended rather than recorded. A second line
    adds a distinct identity for the same target, which pins the sort order
    across warnings that must both survive.
    """
    files = dict(_WARNED_EDGE_FILES)
    files["application/service.py"] = (
        "from pkg.adapters.database import Database, Database as DatabaseAlias\n"
        "import pkg.adapters.database\n"
    )
    result = _check(tmp_path, files, policy=_policy())

    identities = [warning.identity() for warning in result.warnings]

    assert identities == [
        ("HEC001", "pkg.application.service", "pkg.adapters.database", 1),
        ("HEC001", "pkg.application.service", "pkg.adapters.database", 2),
        ("HEC001", "pkg.application.service", "pkg.adapters.database.Database", 1),
    ], f"duplicate edges must collapse and the rest stay sorted, got {identities!r}"


def test_matching_ignore_suppresses_a_warned_edge(tmp_path: Path) -> None:
    """A documented ignore wins over a warning target and counts as matched."""
    result = _warned_edge_result(
        tmp_path,
        policy=_policy(
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.adapters",
                    reason="Tolerated temporarily, superseded by an ignore.",
                ),
            ),
        ),
    )

    assert not result.warnings, (
        f"an ignore must suppress the warning, got {result.warnings!r}"
    )
    assert result.ignored, f"expected the suppression to be reported, got {result!r}"
    assert not result.unmatched_ignores, (
        f"the ignore applied, so it must not read as stale: "
        f"{result.unmatched_ignores!r}"
    )


def test_precedence_allows_before_ignores_and_warns(tmp_path: Path) -> None:
    """One run exercises the whole precedence order at once.

    ``application`` allows ``adapter`` and warns ``legacy``, and the package
    imports both. The allowed edge is silent, the ignore aimed at it stays
    unmatched because allowed edges return before the ignore is consulted
    (which is what keeps a stale ignore detectable), and the warned edge is
    reported without failing -- all from a policy that carries warning targets,
    so an ordering mistake would surface here rather than only in isolation.
    """
    precedence_groups = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain", "adapter"),
            ("legacy",),
        ),
        ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
        ModuleGroup("legacy", ("pkg.legacy",), ("legacy",)),
    )
    files = dict(_WARNED_EDGE_FILES)
    files["legacy/__init__.py"] = ""
    files["legacy/old.py"] = ""
    files["application/service.py"] = (
        "from pkg.adapters.database import Database\nimport pkg.legacy.old\n"
    )
    result = _check(
        tmp_path,
        files,
        policy=_policy(
            groups=precedence_groups,
            ignores=(
                IgnoredImport(
                    importer="pkg.application",
                    imported="pkg.adapters",
                    reason="Applied to an edge that is allowed.",
                ),
            ),
        ),
    )

    assert result.ok, f"neither a warning nor a stale ignore may fail, got {result!r}"
    assert {warning.imported for warning in result.warnings} == {"pkg.legacy.old"}, (
        f"only the warned edge is reported, got {result.warnings!r}"
    )
    assert not result.ignored, (
        f"an allowed edge must not be exempted, got {result.ignored!r}"
    )
    assert result.unmatched_ignores == ("pkg.application -> pkg.adapters",), (
        f"an ignore on an allowed edge must read as stale, got {result!r}"
    )


def test_warning_target_does_not_hide_a_forbidden_edge(tmp_path: Path) -> None:
    """A group that warns one target still forbids its other targets.

    Warning support must not widen the allow-list, so the ``domain`` group's
    import of the adapter stays a violation while ``application``'s becomes a
    warning. Both are checked in one run so the two paths are contrasted.
    """
    files = dict(_WARNED_EDGE_FILES)
    files["domain/model.py"] = "from pkg.adapters.database import Database\n"
    result = _check(tmp_path, files, policy=_policy())

    forbidden = {violation.importer for violation in result.violations}
    warned = {warning.importer for warning in result.warnings}

    assert forbidden == {"pkg.domain.model"}, (
        f"domain importing the adapter must stay forbidden, got {forbidden!r}"
    )
    assert warned == {"pkg.application.service"}, (
        f"only the warned edge may pass through, got {warned!r}"
    )
    assert not result.ok, f"a real violation must still fail the check, got {result!r}"


def test_direct_warning_edge_is_reported(tmp_path: Path) -> None:
    """A direct ``import`` statement is warned on just like a ``from`` import."""
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "application/__init__.py": "",
            "application/service.py": "import pkg.adapters.database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "",
        },
        policy=_policy(),
    )

    imported = {warning.imported for warning in result.warnings}
    assert "pkg.adapters.database" in imported, (
        f"a direct import must reach the warning path, got {imported!r}"
    )


def test_reexport_through_a_barrel_reaches_a_warning_target(tmp_path: Path) -> None:
    """Each expanded re-export target is classified, including warning ones.

    The consumer imports a symbol a barrel re-exports from the adapter group,
    so the edge reaching policy is the origin rather than the barrel. Warnings
    must appear on that same origin, or a re-export would escape the warning
    exactly as it would otherwise escape a violation.
    """
    # ``application`` warns the adapter group because the re-export hands it an
    # adapter origin, and allows the barrel so the consumer's own module edge is
    # not a violation that would mask the warning under test.
    api_warns_adapter = (
        ModuleGroup("domain", ("pkg.domain",), ("domain",)),
        ModuleGroup(
            "application",
            ("pkg.application",),
            ("application", "domain", "api"),
            ("adapter",),
        ),
        ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
        ModuleGroup(
            "api", ("pkg.api",), ("api", "domain", "application"), ("adapter",)
        ),
    )
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "api/__init__.py": _REEXPORT_HIDDEN_FROM_WILDCARDS,
            "api/routes.py": "",
            "application/__init__.py": "",
            "application/service.py": "from pkg.api import Database\n",
            "adapters/__init__.py": "",
            "adapters/database.py": "class Database: ...\n",
            "domain/__init__.py": "",
        },
        policy=_policy(groups=api_warns_adapter),
    )

    assert result.ok, f"a warned re-export must not fail, got {result!r}"
    warned_edges = {(warning.importer, warning.imported) for warning in result.warnings}
    assert ("pkg.api", "pkg.adapters.database.Database") in warned_edges, (
        f"the barrel's own re-export must be warned, got {warned_edges!r}"
    )
    assert ("pkg.application.service", "pkg.adapters.database.Database") in (
        warned_edges
    ), f"the consumer reaching the origin must be warned, got {warned_edges!r}"
