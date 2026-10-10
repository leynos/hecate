"""Property tests for pure Hecate helpers."""

from __future__ import annotations

import ast
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from hecate.all_sequence import literal_all_names
from hecate.config import PackageRoot
from hecate.diagnostics import ArchitectureViolation
from hecate.imports import compute_module_name, relative_import_base
from hecate.namespaces import analyse_namespaces
from hecate.origins import build_origin_index
from hecate.policy import ModuleGroup, first_matching_group

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


def test_origin_index_is_idempotent_for_unchanged_package(tmp_path: Path) -> None:
    """Repeated indexing over unchanged files returns the same mapping."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import Adapter\n", encoding="utf-8"
    )
    (package_root / "adapter.py").write_text("class Adapter: ...\n", encoding="utf-8")
    package = (PackageRoot("pkg", package_root),)

    first = build_origin_index(package, analyse_namespaces(package))
    second = build_origin_index(package, analyse_namespaces(package))

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
