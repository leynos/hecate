"""Property tests for pure Hecate helpers."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from hecate.config import PackageRoot
from hecate.diagnostics import ArchitectureViolation
from hecate.imports import compute_module_name, relative_import_base
from hecate.policy import ModuleGroup, first_matching_group
from hecate.reexports import build_reexport_index

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


def test_reexport_indexing_is_idempotent_for_unchanged_package(tmp_path: Path) -> None:
    """Repeated indexing over unchanged files returns the same mapping."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    (package_root / "__init__.py").write_text(
        "from .adapter import Adapter\n", encoding="utf-8"
    )
    (package_root / "adapter.py").write_text("class Adapter: ...\n", encoding="utf-8")
    package = (PackageRoot("pkg", package_root),)

    first = build_reexport_index(package)
    second = build_reexport_index(package)

    assert first == second, (
        f"expected unchanged package re-export index to be idempotent, "
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
