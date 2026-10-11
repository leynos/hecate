"""Property tests for pure Hecate helpers."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from discovery_fixtures import discover_package_roots
from hypothesis import given
from hypothesis import strategies as st

from hecate.all_sequence import literal_all_names
from hecate.checker import ArchitectureCheckResult
from hecate.config import PackageRoot
from hecate.diagnostics import ArchitectureViolation, ArchitectureWarning
from hecate.imports import compute_module_name, relative_import_base
from hecate.namespaces import analyse_namespaces
from hecate.origins import build_origin_index
from hecate.output import render_json, render_text
from hecate.policy import (
    ModuleGroup,
    ShadowedPrefix,
    find_shadowed_prefixes,
    first_matching_group,
)

IDENTIFIER = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True)


@given(st.lists(IDENTIFIER, min_size=1, max_size=5))
def test_compute_module_name_round_trips_package_relative_paths(
    parts: list[str],
) -> None:
    """Generated package-relative paths round-trip to dotted names."""
    source_path = Path("pkg", *parts).with_suffix(".py")

    module_name = compute_module_name(Path("pkg"), "pkg", source_path)
    expected = ".".join(("pkg", *parts))

    assert module_name == expected, (
        f"expected module name {expected!r} for parts {parts!r}, got {module_name!r}"
    )


@given(st.integers(min_value=1, max_value=4), st.booleans())
def test_relative_import_base_is_consistent(level: int, is_init: bool) -> None:
    """Relative import bases never gain module depth."""
    module_name = "pkg.one.two.three"

    base = relative_import_base(module_name, is_package_init=is_init, level=level)

    assert len(base.split(".")) <= len(module_name.split(".")), (
        f"expected base {base!r} to be no deeper than module {module_name!r}"
    )
    assert module_name.startswith(base), (
        f"expected module {module_name!r} to start with base {base!r}"
    )


@given(IDENTIFIER)
def test_group_classification_is_first_match_deterministic(suffix: str) -> None:
    """Overlapping prefixes classify by first configured group."""
    groups = (
        ModuleGroup("first", ("pkg.domain",), ("first",)),
        ModuleGroup("second", ("pkg",), ("second",)),
    )

    matched = first_matching_group(f"pkg.domain.{suffix}", groups)

    assert matched == groups[0], (
        f"expected first group for overlapping prefix, got {matched!r}"
    )


@given(IDENTIFIER, IDENTIFIER, IDENTIFIER)
def test_shadowed_prefix_records_match_first_group_classification(
    root: str, package: str, child: str
) -> None:
    """Every reported narrow prefix resolves to its earlier winning group."""
    broad_prefix = f"{root}.{package}"
    narrow_prefix = f"{broad_prefix}.{child}"
    groups = (
        ModuleGroup("winner", (broad_prefix,), ("winner",)),
        ModuleGroup("shadowed", (narrow_prefix,), ("shadowed",)),
    )

    shadows = find_shadowed_prefixes(groups)

    assert shadows == (
        ShadowedPrefix(
            shadowed_group="shadowed",
            shadowed_prefix=narrow_prefix,
            winning_group="winner",
            winning_prefix=broad_prefix,
        ),
    ), f"expected the narrow prefix shadow record, got {shadows!r}"
    matched = first_matching_group(narrow_prefix, groups)
    assert matched == groups[0], (
        f"expected winning group {groups[0]!r}, got {matched!r}"
    )


@given(
    root=IDENTIFIER,
    suffixes=st.lists(IDENTIFIER, min_size=2, max_size=2, unique=True),
)
def test_unshadowed_prefixes_with_unique_owners_keep_their_classification(
    root: str, suffixes: list[str]
) -> None:
    """Disjoint sibling prefixes remain owned by their configured groups."""
    first_prefix = f"{root}.{suffixes[0]}"
    second_prefix = f"{root}.{suffixes[1]}"
    groups = (
        ModuleGroup("first", (first_prefix,), ("first",)),
        ModuleGroup("second", (second_prefix,), ("second",)),
    )

    shadows = find_shadowed_prefixes(groups)
    assert not shadows, (
        f"expected disjoint prefixes to stay unshadowed, got {shadows!r}"
    )
    first_match = first_matching_group(first_prefix, groups)
    assert first_match == groups[0], (
        f"expected {first_prefix!r} to match {groups[0]!r}, got {first_match!r}"
    )
    second_match = first_matching_group(second_prefix, groups)
    assert second_match == groups[1], (
        f"expected {second_prefix!r} to match {groups[1]!r}, got {second_match!r}"
    )


def test_origin_index_is_idempotent_for_unchanged_package(tmp_path: Path) -> None:
    """Repeated indexing over unchanged files returns the same mapping."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import Adapter\n", encoding="utf-8"
    )
    (package_root / "adapter.py").write_text("class Adapter: ...\n", encoding="utf-8")
    package = (PackageRoot("pkg", package_root),)

    first = build_origin_index(
        package, analyse_namespaces(discover_package_roots(package))
    )
    second = build_origin_index(
        package, analyse_namespaces(discover_package_roots(package))
    )

    assert first == second, (
        f"expected unchanged package origin index to be idempotent, "
        f"got {first!r} then {second!r}"
    )


@given(st.lists(IDENTIFIER, min_size=1, max_size=5))
def test_duplicate_imports_do_not_create_duplicate_identities(
    names: list[str],
) -> None:
    """Duplicate imported names collapse under violation identity sorting."""
    names_with_duplicate = [*names, names[0]]
    identities = {
        ArchitectureViolation(
            rule_id="HEC001",
            importer="pkg.domain.model",
            imported=f"pkg.adapters.{name}",
            importer_group="domain",
            imported_group="adapter",
            source_path=Path("pkg/domain/model.py"),
            line=1,
        ).identity()
        for name in names_with_duplicate
    }

    assert len(identities) < len(names_with_duplicate), (
        f"expected duplicate imports to collapse, got {len(identities)} identities "
        f"from {len(names_with_duplicate)} names"
    )


def test_text_json_diagnostics_preserve_violation_identity(tmp_path: Path) -> None:
    """Diagnostic dictionaries preserve fields used by text identity."""
    violation = ArchitectureViolation(
        rule_id="HEC001",
        importer="pkg.domain.model",
        imported="pkg.adapters.db",
        importer_group="domain",
        imported_group="adapter",
        source_path=tmp_path / "pkg/domain/model.py",
        line=9,
    )

    payload = violation.to_dict()

    identity = violation.identity()
    assert payload["rule_id"] == identity[0], (
        f"expected rule_id {identity[0]!r}, got {payload['rule_id']!r}"
    )
    assert payload["importer"] == identity[1], (
        f"expected importer {identity[1]!r}, got {payload['importer']!r}"
    )
    assert payload["imported"] == identity[2], (
        f"expected imported {identity[2]!r}, got {payload['imported']!r}"
    )
    assert payload["line"] == identity[3], (
        f"expected line {identity[3]!r}, got {payload['line']!r}"
    )


def _warning_for(name: str, line: int) -> ArchitectureWarning:
    """Return a warning diagnostic for one imported module and source line."""
    return ArchitectureWarning(
        rule_id="HEC001",
        importer="pkg.application.service",
        imported=f"pkg.adapters.{name}",
        importer_group="application",
        imported_group="adapter",
        source_path=Path("pkg/application/service.py"),
        line=line,
    )


@given(st.lists(IDENTIFIER, min_size=1, max_size=4))
def test_text_and_json_preserve_every_warning_identity(names: list[str]) -> None:
    """Each warning keeps its identity through both renderers.

    The two renderers are the only views a consumer has of a warning, and the
    identity fields are what a consumer keys on. Generating several warnings
    makes the assertion cover the whole rendered collection rather than a
    single entry whose position happened to be stable.
    """
    warnings = tuple(_warning_for(name, line) for line, name in enumerate(names, 1))
    result = ArchitectureCheckResult(violations=(), warnings=warnings)

    text_output = render_text(result)
    entries = json.loads(render_json(result))["warnings"]

    assert len(entries) == len(warnings), (
        f"expected one JSON entry per warning, got {entries!r}"
    )
    for warning, entry in zip(warnings, entries, strict=True):
        rule_id, importer, imported, line = warning.identity()
        assert entry["rule_id"] == rule_id, (
            f"expected rule_id {rule_id!r}, got {entry['rule_id']!r}"
        )
        assert entry["importer"] == importer, (
            f"expected importer {importer!r}, got {entry['importer']!r}"
        )
        assert entry["imported"] == imported, (
            f"expected imported {imported!r}, got {entry['imported']!r}"
        )
        assert entry["line"] == line, f"expected line {line!r}, got {entry['line']!r}"
        assert f"{importer}:{line}" in text_output, (
            f"expected {importer}:{line} in text output, got {text_output!r}"
        )
        assert imported in text_output, (
            f"expected {imported} in text output, got {text_output!r}"
        )


@given(st.lists(IDENTIFIER, min_size=1, max_size=5))
def test_renderers_preserve_warning_order(names: list[str]) -> None:
    """Renderers preserve the order warnings arrive in, and drop none.

    ``check_architecture`` sorts and de-duplicates warnings before they reach a
    result, so canonical ordering is the checker's job. A renderer that
    reordered instead would undo that determinism, and one that dropped entries
    would silently hide a tolerated edge; ordering both halves from one
    generated collection also pins that text and JSON agree on which warning
    came first.
    """
    warnings = tuple(_warning_for(name, line) for line, name in enumerate(names, 1))
    result = ArchitectureCheckResult(violations=(), warnings=warnings)

    entries = json.loads(render_json(result))["warnings"]
    assert [entry["imported"] for entry in entries] == [
        warning.imported for warning in warnings
    ], f"JSON reordered or dropped warnings: {entries!r}"

    text_output = render_text(result)
    positions = [
        text_output.index(f"{warning.importer}:{warning.line}") for warning in warnings
    ]
    assert positions == sorted(positions), (
        f"text output reordered the warnings: {text_output!r}"
    )


_ALL_OPERATIONS = st.one_of(
    st.tuples(st.just("literal"), st.lists(IDENTIFIER, max_size=3)),
    st.tuples(st.just("augmented"), st.lists(IDENTIFIER, max_size=3)),
    st.tuples(st.just("unknown"), st.just(())),
    st.tuples(st.just("conditional"), st.lists(IDENTIFIER, max_size=3)),
)


def _render_all_assignments(operations: list[tuple[str, list[str]]]) -> str:
    """Render a generated operation sequence as module source."""
    lines: list[str] = ["class Thing: ...\n"]
    for kind, names in operations:
        literal = "[" + ", ".join(f"'{name}'" for name in names) + "]"
        if kind == "literal":
            lines.append(f"__all__ = {literal}\n")
        elif kind == "augmented":
            lines.append(f"__all__ += {literal}\n")
        elif kind == "conditional":
            lines.append(f"if True:\n    __all__ = {literal}\n")
        else:
            lines.append("__all__ = tuple(__name__)\n")
    return "".join(lines)


def _fold_all_step(
    names: tuple[str, ...] | None, operation: tuple[str, list[str]]
) -> tuple[str, ...] | None:
    """Return the known ``__all__`` value after one generated operation.

    Each operation is a rule about what survives: a literal replaces whatever
    was known, an augmented assignment extends only a known sequence, and
    anything unreadable or branch-scoped clears the value.
    """
    kind, additions = operation
    if kind == "literal":
        return tuple(additions)
    if kind == "augmented":
        return None if names is None else (*names, *additions)
    return None


def _fold_all_reference(
    operations: list[tuple[str, list[str]]],
) -> tuple[str, ...] | None:
    """Return the expected ``__all__`` value, as an independent reference fold.

    This restates the model in a few lines so the test compares the production
    evaluator against a second implementation rather than against itself.
    """
    names: tuple[str, ...] | None = None
    for operation in operations:
        names = _fold_all_step(names, operation)
    return names


@given(st.lists(_ALL_OPERATIONS, max_size=6))
def test_all_sequence_evaluation_matches_a_reference_fold(
    operations: list[tuple[str, list[str]]],
) -> None:
    """The analyser's ``__all__`` result matches an independent reference fold.

    Reading the sequence statically is subtle because three different
    operations interact: a literal replaces, an augmented assignment extends
    only what is already known, and anything unreadable or branch-scoped
    clears the known value. Comparing against a small reference fold catches a
    change that makes one of those overwrite the others.
    """
    tree = ast.parse(_render_all_assignments(operations))

    assert literal_all_names(tree) == _fold_all_reference(operations), (
        f"__all__ evaluation disagreed with the reference fold for {operations!r}"
    )
