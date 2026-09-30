"""Unit tests for diagnostic rendering and coverage visibility."""

from __future__ import annotations

import json
from pathlib import Path

from hecate.checker import ArchitectureCheckResult
from hecate.diagnostics import ArchitectureViolation, CoverageDiagnostic
from hecate.output import render_json, render_text
from hecate.policy import EdgeState, Severity


def test_text_and_json_output_include_violation_identity(tmp_path: Path) -> None:
    """Diagnostic renderers preserve the same violation identity."""
    violation = ArchitectureViolation(
        rule_id="HEC001",
        importer="pkg.domain.model",
        imported="pkg.adapters.db",
        importer_group="domain",
        imported_group="adapter",
        source_path=tmp_path / "pkg/domain/model.py",
        line=1,
    )
    result = ArchitectureCheckResult(violations=(violation,))

    text_output = render_text(result)
    json_output = json.loads(render_json(result))

    assert "pkg.domain.model:1" in text_output, (
        f"expected text output to include violation location, got {text_output!r}"
    )
    assert json_output["violations"][0]["rule_id"] == "HEC001", (
        f"expected JSON rule_id HEC001, got {json_output!r}"
    )
    assert json_output["violations"][0]["importer"] == "pkg.domain.model", (
        f"expected JSON importer pkg.domain.model, got {json_output!r}"
    )
    assert json_output["violations"][0]["imported"] == "pkg.adapters.db", (
        f"expected JSON imported pkg.adapters.db, got {json_output!r}"
    )
    assert json_output["violations"][0]["line"] == 1, (
        f"expected JSON line 1, got {json_output!r}"
    )


def test_json_output_reports_coverage_by_default(tmp_path: Path) -> None:
    """JSON output carries a coverage section so machine consumers see it."""
    result = ArchitectureCheckResult(violations=())

    payload = json.loads(render_json(result))

    assert payload["coverage"] == [], (
        f"expected an empty coverage list, got {payload!r}"
    )
    assert payload["ok"] is True, f"expected a passing payload, got {payload!r}"


def test_text_output_hides_coverage_warnings_by_default(tmp_path: Path) -> None:
    """Text output keeps its existing shape unless coverage is requested."""
    diagnostic = CoverageDiagnostic(
        state=EdgeState.UNCLASSIFIED,
        severity=Severity.WARNING,
        rule_id="HEC001",
        importer="pkg.application.service",
        imported="pkg.newthing",
        source_path=tmp_path / "pkg/application/service.py",
        line=3,
        importer_group="application",
    )
    result = ArchitectureCheckResult(violations=(), coverage=(diagnostic,))

    default_output = render_text(result)
    verbose_output = render_text(result, show_coverage=True)

    assert "unclassified" not in default_output, (
        f"expected coverage to stay hidden by default, got {default_output!r}"
    )
    assert "unclassified" in verbose_output, (
        f"expected coverage behind the flag, got {verbose_output!r}"
    )
    assert "pkg.newthing" in verbose_output, (
        f"expected the unclassified target to be named, got {verbose_output!r}"
    )


def test_coverage_failure_always_renders_and_fails_the_check(tmp_path: Path) -> None:
    """A coverage failure changes the exit code, so it is always rendered."""
    diagnostic = CoverageDiagnostic(
        state=EdgeState.UNRESOLVED,
        severity=Severity.ERROR,
        rule_id="HEC001",
        importer="pkg.application.service",
        imported="pkg.domain.missing",
        source_path=tmp_path / "pkg/application/service.py",
        line=3,
        importer_group="application",
        imported_group="domain",
    )
    result = ArchitectureCheckResult(violations=(), coverage=(diagnostic,))

    output = render_text(result)

    assert not result.ok, f"an error-severity coverage entry must fail, got {result!r}"
    assert "unresolved" in output, (
        f"expected the coverage failure in text output, got {output!r}"
    )
    assert "architecture check passed" not in output, (
        f"expected no pass message, got {output!r}"
    )
