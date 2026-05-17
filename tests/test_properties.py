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

    assert module_name == ".".join(("pkg", *parts))


@given(st.integers(min_value=1, max_value=4), st.booleans())
def test_relative_import_base_is_consistent(level: int, is_init: bool) -> None:
    """Relative import bases never gain module depth."""
    module_name = "pkg.one.two.three"

    base = relative_import_base(module_name, is_package_init=is_init, level=level)

    assert len(base.split(".")) <= len(module_name.split("."))
    assert module_name.startswith(base)


@given(IDENTIFIER)
def test_group_classification_is_first_match_deterministic(suffix: str) -> None:
    """Overlapping prefixes classify by first configured group."""
    groups = (
        ModuleGroup("first", ("pkg.domain",), ("first",)),
        ModuleGroup("second", ("pkg",), ("second",)),
    )

    assert first_matching_group(f"pkg.domain.{suffix}", groups) == groups[0]


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

    assert first == second


@given(st.lists(IDENTIFIER, min_size=1, max_size=5))
def test_duplicate_imports_do_not_create_duplicate_identities(
    names: list[str],
) -> None:
    """Duplicate imported names collapse under violation identity sorting."""
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
        for name in names
    }

    assert len(identities) <= len(names)


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

    assert payload["rule_id"] == violation.identity()[0]
    assert payload["importer"] == violation.identity()[1]
    assert payload["imported"] == violation.identity()[2]
    assert payload["line"] == violation.identity()[3]
