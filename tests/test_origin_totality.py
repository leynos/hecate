"""Property tests for the totality of policy edge outcomes.

Each in-scope import edge must end in exactly one documented state, and the
aggregate result the CLI acts on must agree with the diagnostics the checker
recorded. These properties generate policies over a fixed package and compare
the checker against an independent reference model of the documented rules, so
a classification change has to disagree with a second implementation rather
than with itself.
"""

from __future__ import annotations

import collections.abc as cabc
import contextlib
import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import HecateConfig, PackageRoot
from hecate.policy import (
    ArchitecturePolicy,
    EdgeState,
    IgnoredImport,
    ModuleGroup,
    Severity,
    first_matching_group,
    ignore_matches,
)

#: The states an in-scope edge can end in, as the model documents them.
_IN_SCOPE_STATES = frozenset(EdgeState)

#: The severities a diagnostic can carry.
_SEVERITIES = frozenset(Severity)

_TOTALITY_FILES = {
    "__init__.py": "",
    "domain/__init__.py": "",
    "domain/sibling.py": "",
    "domain/model.py": (
        "from ..adapters import db\n"
        "from . import sibling\n"
        "from .. import mystery\n"
        "import os\n"
    ),
    "adapters/__init__.py": "",
    "adapters/db.py": "",
    "mystery.py": "",
}

_DOMAIN = ModuleGroup("domain", ("pkg.domain",), ())
_DOMAIN_OPEN = ModuleGroup("domain", ("pkg.domain",), ("domain",))
_ADAPTER = ModuleGroup("adapter", ("pkg.adapters",), ())
_MISC = ModuleGroup("misc", ("pkg.mystery",), ())

_GROUPS = st.lists(
    st.sampled_from((_DOMAIN, _DOMAIN_OPEN, _ADAPTER, _MISC)),
    max_size=4,
    unique=True,
)

#: The import targets ``domain/model.py`` writes, as the checker sees them.
_INTERNAL_TARGETS = (
    "pkg.domain.sibling",
    "pkg.mystery",
    "pkg.adapters.db",
    "pkg.adapters",
    "pkg.domain",
    "pkg",
)

_IMPORTER = "pkg.domain.model"


def _reference_outcome(
    target: str,
    groups: list[ModuleGroup],
    ignores: tuple[IgnoredImport, ...],
) -> EdgeState:
    """Return the outcome the policy rules imply for one import target.

    This is the independent reference model the totality property compares the
    checker against. It restates the documented rules in a few lines — a
    permitted edge is silent, an unclassified one reports coverage, a
    documented ignore wins over any non-permitted outcome — so the property
    measures the checker rather than re-asserting whatever it happened to
    produce.
    """
    importer_group = first_matching_group(_IMPORTER, tuple(groups))
    imported_group = first_matching_group(target, tuple(groups))
    if importer_group is None or imported_group is None:
        outcome = EdgeState.UNCLASSIFIED
    elif imported_group.name in importer_group.allowed:
        outcome = EdgeState.PERMITTED
    else:
        outcome = EdgeState.FORBIDDEN
    if outcome is EdgeState.PERMITTED:
        return outcome
    covered = any(ignore_matches(ignored, _IMPORTER, target) for ignored in ignores)
    return EdgeState.EXEMPTED if covered else outcome


def _write_totality_package(root: Path) -> PackageRoot:
    """Write the fixed fixture package used by the totality properties."""
    package_root = root / "pkg"
    for relative_path, contents in _TOTALITY_FILES.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return PackageRoot("pkg", package_root)


@contextlib.contextmanager
def _checked(
    groups: list[ModuleGroup],
    *,
    strict: bool,
    ignores: tuple[IgnoredImport, ...] = (),
) -> cabc.Iterator[ArchitectureCheckResult]:
    """Check the fixture package against a generated policy in its own directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = HecateConfig(
            packages=(_write_totality_package(Path(tmp_dir)),),
            policy=ArchitecturePolicy(
                groups=tuple(groups), ignores=ignores, strict=strict
            ),
        )
        yield check_architecture(config)


def _outcomes(result: ArchitectureCheckResult) -> dict[tuple[str, str], EdgeState]:
    """Return the single outcome recorded for each edge.

    A collision here means one edge was reported twice under different states,
    which the identity-keyed dictionaries in the checker are supposed to
    prevent. ``setdefault`` plus the length check in the caller asserts that.
    """
    outcomes: dict[tuple[str, str], EdgeState] = {}
    for violation in result.violations:
        outcomes[violation.importer, violation.imported] = EdgeState.FORBIDDEN
    for ignored in result.ignored:
        outcomes.setdefault((ignored.importer, ignored.imported), EdgeState.EXEMPTED)
    for diagnostic in result.coverage:
        outcomes.setdefault(
            (diagnostic.importer, diagnostic.imported), diagnostic.state
        )
    return outcomes


@given(_GROUPS, st.booleans())
def test_every_in_scope_edge_gets_exactly_one_outcome(
    groups: list[ModuleGroup],
    has_ignore: bool,
) -> None:
    """Each in-scope edge becomes exactly one violation, exemption, or coverage.

    A policy that relied on an absent diagnostic to mean "permitted" could hide
    an edge it never looked at. Counting outcomes instead makes the model
    total: the fixture's internal edges must all be accounted for, whatever
    groups the policy configures and whether or not an ignore covers one of
    them. The external ``os`` import is the documented exception, and asserting
    its absence pins the scope boundary in the other direction.
    """
    ignores = (
        (
            IgnoredImport(
                importer="pkg.domain.model", imported="pkg.adapters", reason="r"
            ),
        )
        if has_ignore
        else ()
    )
    with _checked(groups, strict=True, ignores=ignores) as result:
        outcomes = _outcomes(result)

    total = len(result.violations) + len(result.ignored) + len(result.coverage)
    assert len(outcomes) == total, (
        f"an edge must have exactly one outcome for "
        f"groups={[group.name for group in groups]!r} has_ignore={has_ignore}: "
        f"{total} diagnostics collapsed to {len(outcomes)} edges"
    )
    recorded = set(outcomes.values())
    assert recorded <= _IN_SCOPE_STATES, (
        f"an outcome outside the documented states appeared: {recorded!r}"
    )

    recorded_edges = set(outcomes)
    assert all(importer == _IMPORTER for importer, _ in recorded_edges), (
        f"only the model module imports anything here, got {recorded_edges!r}"
    )
    assert not any(imported == "os" for _, imported in recorded_edges), (
        f"an external edge must stay out of scope, got {recorded_edges!r}"
    )
    assert not any(
        diagnostic.state is EdgeState.EXEMPTED for diagnostic in result.coverage
    ), "an exempted edge is reported as an ignore, not as coverage"

    for target in _INTERNAL_TARGETS:
        expected = _reference_outcome(target, groups, ignores)
        recorded = outcomes.get((_IMPORTER, target))
        if expected is EdgeState.PERMITTED:
            assert recorded is None, (
                f"a permitted edge must produce no diagnostic: "
                f"{_IMPORTER} -> {target} got {recorded!r} for "
                f"groups={[group.name for group in groups]!r} ignores={ignores!r}"
            )
        else:
            assert recorded is expected, (
                f"{_IMPORTER} -> {target} should be {expected!r} for "
                f"groups={[group.name for group in groups]!r} ignores={ignores!r}, "
                f"got {recorded!r}"
            )


@given(_GROUPS, st.booleans(), st.booleans())
def test_edge_outcomes_stay_inside_the_documented_state_set(
    groups: list[ModuleGroup],
    strict: bool,
    has_ignore: bool,
) -> None:
    """Generated policies only ever produce documented states and severities.

    ``ok``, the exit code, and the rendered report are all derived from these
    values, so a state or severity outside the documented sets would be an
    outcome no renderer knows how to describe. The ``ok`` assertion is the
    totality claim in the other direction: whatever the policy, the aggregate
    result must agree exactly with the diagnostics it carries.
    """
    ignores = (
        (IgnoredImport(importer="pkg.domain", imported="pkg", reason="r"),)
        if has_ignore
        else ()
    )
    with _checked(groups, strict=strict, ignores=ignores) as result:
        states = {diagnostic.state for diagnostic in result.coverage}
        severities = {diagnostic.severity for diagnostic in result.coverage}
        failures = result.coverage_failures
        is_ok = result.ok
        counts = (len(result.violations), len(result.coverage_failures))

    assert states <= _IN_SCOPE_STATES, (
        f"coverage reported an undocumented state {states!r} for "
        f"groups={[group.name for group in groups]!r} strict={strict}"
    )
    assert severities <= _SEVERITIES, (
        f"a severity outside the documented set appeared for strict={strict}: "
        f"{severities!r}"
    )
    assert failures == tuple(
        diagnostic for diagnostic in result.coverage if diagnostic.is_failure
    ), "coverage failures must be exactly the failing coverage entries"
    assert is_ok == (not result.violations and not result.coverage_failures), (
        f"ok disagreed with the recorded diagnostics for groups="
        f"{[group.name for group in groups]!r} strict={strict}: "
        f"{counts[0]} violations, {counts[1]} coverage failures"
    )
