"""Unit tests for the unclassified-module policy.

``unclassified_modules`` answers a different question from coverage of the
import graph: not "was every edge classified?" but "does some group claim every
discovered module?". A module no group claims is enforced over nothing, so its
imports escape the policy until an edge's other endpoint happens to expose
them. These tests pin the three modes, the classification boundary that decides
what counts as claimed, and the guarantee that edge checking is untouched by
the extra pass.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.diagnostics import UnclassifiedModuleDiagnostic
from hecate.policy import (
    ArchitecturePolicy,
    ModuleGroup,
    Severity,
    UnclassifiedModules,
)

_SAMPLE_GROUPS = (
    ModuleGroup("domain", ("pkg.domain",), ("domain",)),
    ModuleGroup("application", ("pkg.application",), ("application", "domain", "api")),
    ModuleGroup("adapter", ("pkg.adapters",), ("adapter",)),
    ModuleGroup("api", ("pkg.api",), ("api", "domain", "application", "adapter")),
)


def _build_package(root: Path, files: dict[str, str]) -> None:
    """Write a scratch package tree from relative paths to source text."""
    for relative_path, contents in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(contents), encoding="utf-8")


def _policy(
    *,
    groups: tuple[ModuleGroup, ...] = _SAMPLE_GROUPS,
    unclassified_modules: UnclassifiedModules = "ignore",
) -> ArchitecturePolicy:
    """Return a policy varying only the knobs these tests exercise."""
    return ArchitecturePolicy(
        groups=groups,
        unclassified_modules=unclassified_modules,
    )


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


#: A package tree whose every module, including the root initializer, is
#: claimed by policy. The initializer is claimed by containment rather than by
#: a group of its own, which is the configuration a conventional project
#: declares. Nothing here may be reported as unclassified.
_FULLY_CLASSIFIED_TREE = {
    "__init__.py": "",
    "domain/__init__.py": "",
    "domain/model.py": "",
    "adapters/__init__.py": "",
    "adapters/database.py": "",
}

#: The same tree plus a package no group claims, carrying both a module with an
#: import and one without. ``newfeature`` imports a classified module, while
#: ``newfeature.helper`` and the root ``__init__.py`` import nothing: an
#: unclassified module must be reported whether or not it imports anything.
_TREE_WITH_NEW_PACKAGE = {
    **_FULLY_CLASSIFIED_TREE,
    "newfeature/__init__.py": "from pkg.domain import model\n",
    "newfeature/helper.py": "",
}

_UNCLASSIFIED_BY_MODE: dict[UnclassifiedModules, Severity | None] = {
    "ignore": None,
    "warn": Severity.WARNING,
    "error": Severity.ERROR,
}


def _unclassified_by_module(
    result: ArchitectureCheckResult,
) -> dict[str, UnclassifiedModuleDiagnostic]:
    return {diagnostic.module: diagnostic for diagnostic in result.unclassified_modules}


@pytest.mark.parametrize(
    "mode", ["ignore", "warn", "error"], ids=["ignore", "warn", "error"]
)
def test_fully_classified_tree_reports_no_unclassified_modules(
    tmp_path: Path, mode: UnclassifiedModules
) -> None:
    """A tree every group covers stays quiet in every mode.

    ``error`` is the decisive case: if classification were even slightly
    over-eager about reporting, a correctly declared project could not adopt
    the strictest setting.
    """
    result = _check(
        tmp_path,
        _FULLY_CLASSIFIED_TREE,
        policy=_policy(unclassified_modules=mode),
    )

    assert not result.unclassified_modules, (
        f"{mode}: a fully classified tree must report nothing, "
        f"got {result.unclassified_modules!r}"
    )
    assert result.ok, f"{mode}: a fully classified tree must pass, got {result!r}"


@pytest.mark.parametrize(
    "mode", ["ignore", "warn", "error"], ids=["ignore", "warn", "error"]
)
def test_new_package_is_reported_at_the_configured_severity(
    tmp_path: Path, mode: UnclassifiedModules
) -> None:
    """A newly added package is named in ``warn`` and ``error`` modes only.

    Both import-free modules are asserted as well as the importing one, because
    the failure mode this feature exists to close is a package that imports
    nothing yet and so would never surface through an edge.
    """
    result = _check(
        tmp_path, _TREE_WITH_NEW_PACKAGE, policy=_policy(unclassified_modules=mode)
    )

    expected_severity = _UNCLASSIFIED_BY_MODE[mode]
    reported = _unclassified_by_module(result)
    if expected_severity is None:
        assert not reported, (
            f"{mode}: the default must report no unclassified module, got {reported!r}"
        )
        assert result.ok, f"{mode}: the default must pass, got {result!r}"
        return
    assert set(reported) == {"pkg.newfeature", "pkg.newfeature.helper"}, (
        f"{mode}: expected every unclassified module, got {sorted(reported)}"
    )
    for diagnostic in reported.values():
        assert diagnostic.rule_id == "HEC002", (
            f"{mode}: module diagnostics carry their own rule id, got {diagnostic!r}"
        )
        assert diagnostic.severity is expected_severity, (
            f"{mode}: expected severity {expected_severity}, got {diagnostic!r}"
        )
    assert result.ok is (expected_severity is Severity.WARNING), (
        f"{mode}: only error severity may fail the check, got {result!r}"
    )


def test_classified_modules_are_not_reported(tmp_path: Path) -> None:
    """Only the unclassified package is named, not its classified siblings."""
    result = _check(
        tmp_path, _TREE_WITH_NEW_PACKAGE, policy=_policy(unclassified_modules="error")
    )

    reported = _unclassified_by_module(result)
    for classified in (
        "pkg.domain",
        "pkg.domain.model",
        "pkg.adapters",
        "pkg.adapters.database",
    ):
        assert classified not in reported, (
            f"{classified} matches a group and must not be reported: {sorted(reported)}"
        )


def test_package_initializer_is_claimed_by_its_subpackages(tmp_path: Path) -> None:
    """Specific groups classify the root initializer without a root group.

    A conventional package has specific groups such as ``pkg.domain`` but no
    group for ``pkg`` itself. The initializer imports and re-exports what its
    subpackages bind, so the policy already governs it; reporting ``pkg`` would
    force a recursive ``pkg`` group, and that group would classify every future
    subpackage the module pass exists to detect.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "domain/model.py": "",
        },
        policy=_policy(groups=_SAMPLE_GROUPS, unclassified_modules="error"),
    )

    assert not result.unclassified_modules, (
        "a root initializer covered by a subpackage group must not be reported, "
        f"got {result.unclassified_modules!r}"
    )
    assert result.ok, f"the check must pass without a catch-all group, got {result!r}"


def test_package_initializer_does_not_claim_a_new_subpackage(tmp_path: Path) -> None:
    """Covering the root initializer must not classify everything beneath it.

    This is the other half of the containment rule: ``pkg`` is claimed because
    ``pkg.domain`` is, but ``pkg.newfeature`` matches no group and must still be
    reported.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "domain/model.py": "",
            "newfeature/__init__.py": "",
            "newfeature/helper.py": "",
        },
        policy=_policy(groups=_SAMPLE_GROUPS, unclassified_modules="error"),
    )

    reported = set(_unclassified_by_module(result))
    assert reported == {"pkg.newfeature", "pkg.newfeature.helper"}, (
        f"a new subpackage must stay visible: {sorted(reported)}"
    )
    assert not result.ok, f"an unclassified subpackage must fail: {result!r}"


def test_group_prefix_does_not_classify_a_lookalike_sibling(tmp_path: Path) -> None:
    """``pkg.domain`` must not classify ``pkg.domainx``.

    Prefix matching happens at a dotted boundary. A substring match would let a
    lookalike package inherit its neighbour's group and pass as classified,
    which is the silent-coverage failure this feature reports.
    """
    result = _check(
        tmp_path,
        {
            "domain/__init__.py": "",
            "domain/model.py": "",
            "domainx/__init__.py": "",
            "domainx/plugin.py": "",
            "__init__.py": "",
        },
        policy=_policy(unclassified_modules="error"),
    )

    reported = set(_unclassified_by_module(result))
    assert reported == {"pkg.domainx", "pkg.domainx.plugin"}, (
        f"a lookalike sibling must not inherit the pkg.domain group: {sorted(reported)}"
    )


def test_unclassified_modules_are_deterministic_across_runs(tmp_path: Path) -> None:
    """Two runs over one tree produce an equal, ordered result.

    Text and JSON output are snapshotted, so the finding order may not depend
    on filesystem iteration order.
    """
    policy = _policy(unclassified_modules="error")

    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    first = _check(first_root, _TREE_WITH_NEW_PACKAGE, policy=policy)
    second = _check(second_root, _TREE_WITH_NEW_PACKAGE, policy=policy)

    modules = [diagnostic.module for diagnostic in first.unclassified_modules]
    assert modules == sorted(modules), f"findings must be sorted, got {modules!r}"
    # Compare each finding as the path the two runs have in common. Rewriting
    # the absolute path would also rewrite an unrelated "b" in ``tmp_path``,
    # making the assertion pass or fail on where pytest happened to put the
    # tree rather than on what Hecate reported.
    assert [
        (item.module, item.source_path.relative_to(first_root))
        for item in first.unclassified_modules
    ] == [
        (item.module, item.source_path.relative_to(second_root))
        for item in second.unclassified_modules
    ], (
        "identical trees must classify identically: "
        f"{first.unclassified_modules!r} vs {second.unclassified_modules!r}"
    )


def _violation_identity(
    result: ArchitectureCheckResult,
) -> list[tuple[str, str, str, int]]:
    return [violation.identity() for violation in result.violations]


@pytest.mark.parametrize(
    "mode", ["ignore", "warn", "error"], ids=["ignore", "warn", "error"]
)
def test_forbidden_edges_are_unaffected_by_the_mode(
    tmp_path: Path, mode: UnclassifiedModules
) -> None:
    """A forbidden import reports the same violation in every mode.

    The classification pass must not disturb edge checking, so the violation
    set is pinned across all three settings.
    """
    files = {
        "__init__.py": "",
        "domain/__init__.py": "",
        "domain/model.py": "from pkg.adapters.database import Database\n",
        "adapters/__init__.py": "",
        "adapters/database.py": "class Database: ...\n",
        "application/__init__.py": "",
        "api/__init__.py": "",
    }

    result = _check(tmp_path, files, policy=_policy(unclassified_modules=mode))

    # ``from pkg.adapters.database import Database`` reaches both the module and
    # the symbol it names, and both are forbidden here: the module edge because
    # domain may not import the adapter group, the symbol edge because that
    # group is where the name resolves.
    assert _violation_identity(result) == [
        ("HEC001", "pkg.domain.model", "pkg.adapters.database", 1),
        ("HEC001", "pkg.domain.model", "pkg.adapters.database.Database", 1),
    ], f"{mode}: the edge policy must be unchanged, got {result.violations!r}"
    assert not result.ok, f"{mode}: a forbidden import must still fail, got {result!r}"


def test_external_imports_do_not_become_unclassified_modules(tmp_path: Path) -> None:
    """An external dependency is never reported as an unclassified module.

    The pass applies only to modules discovered beneath the configured roots.
    External imports stay governed by ``include_external_packages`` and the
    prefixes a group claims, so an unclaimed library remains out of scope.
    """
    result = _check(
        tmp_path,
        {
            "__init__.py": "",
            "domain/__init__.py": "",
            "domain/model.py": "import sqlalchemy\n",
        },
        policy=_policy(
            groups=(ModuleGroup("domain", ("pkg.domain",), ("domain",)),),
            unclassified_modules="error",
        ),
    )

    reported = set(_unclassified_by_module(result))
    assert not reported, (
        f"an external import must not be reported as a module, got {sorted(reported)}"
    )


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (Severity.ERROR, True),
        (Severity.WARNING, False),
        (Severity.EXEMPT, False),
    ],
    ids=["error", "warning", "exempt"],
)
def test_exported_module_diagnostic_answers_is_failure(
    severity: Severity, *, expected: bool
) -> None:
    """``UnclassifiedModuleDiagnostic.is_failure`` is part of the public surface.

    The class is exported from ``hecate``, so a consumer can ask a diagnostic
    it holds whether the run fails. The predicate that decides it is defined
    once for both severity-carrying diagnostics; this pins the attribute the
    package promises, rather than only the internal call rule, so a refactor
    that deleted the property in favour of a free function would fail here
    instead of breaking a downstream caller with ``AttributeError``.
    """
    diagnostic = UnclassifiedModuleDiagnostic(
        module="pkg.newfeature",
        source_path=Path("pkg/newfeature/__init__.py"),
        severity=severity,
    )

    assert diagnostic.is_failure is expected, (
        f"severity {severity} must report is_failure={expected}, "
        f"got {diagnostic.is_failure}"
    )
