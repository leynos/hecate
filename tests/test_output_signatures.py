"""Public-surface tests for the diagnostic renderers.

These live apart from the per-diagnostic rendering tests because they pin the
call contract rather than a rendering rule: the keyword-only parameters both
renderers shipped before warning support, and the result field that carries the
command outcome so neither signature had to grow.
"""

from __future__ import annotations

import json
from pathlib import Path

from hecate.checker import ArchitectureCheckResult
from hecate.diagnostics import (
    ArchitectureViolation,
    CoverageDiagnostic,
    IgnoredImportDiagnostic,
)
from hecate.output import render_json, render_text
from hecate.policy import EdgeState, Severity


def test_renderers_keep_their_keyword_arguments(tmp_path: Path) -> None:
    """The pre-warning keyword surface stays callable.

    Both renderers shipped with keyword-only flags before warning support
    existed, and a caller that passes one has no reason to expect a type error.
    This exercises every keyword those signatures accepted, so a future
    refactor cannot reintroduce the regression Codex found.
    """
    ignored = IgnoredImportDiagnostic(
        importer="pkg.domain.model",
        imported="pkg.adapters.db",
        reason="documented boundary violation",
    )
    diagnostic = CoverageDiagnostic(
        state=EdgeState.UNCLASSIFIED,
        severity=Severity.WARNING,
        rule_id="HEC001",
        importer="pkg.application.service",
        imported="pkg.newthing",
        source_path=tmp_path / "pkg/application/service.py",
        line=3,
    )
    result = ArchitectureCheckResult(
        violations=(), ignored=(ignored,), coverage=(diagnostic,)
    )

    text_output = render_text(result, show_ignored=True, show_coverage=True)
    payload = json.loads(
        render_json(
            result,
            show_ignored=True,
            show_coverage=True,
            include_unclassified=True,
        )
    )

    assert "documented boundary violation" in text_output, (
        f"expected show_ignored to reach the text renderer, got {text_output!r}"
    )
    assert "pkg.newthing" in text_output, (
        f"expected show_coverage to reach the text renderer, got {text_output!r}"
    )
    assert payload["ignored"][0]["importer"] == "pkg.domain.model", (
        f"expected show_ignored to reach the JSON renderer, got {payload!r}"
    )
    assert payload["unclassified_modules"] == [], (
        f"expected include_unclassified to reach JSON, got {payload!r}"
    )


def test_renderers_report_the_command_outcome_from_the_result(
    tmp_path: Path,
) -> None:
    """``result.passed`` overrides the architecture outcome in both formats.

    The CLI records the exit-code decision on the result so the renderers can
    keep their existing signatures. A consumer that sets it must see the
    enforcing run reported as failed while ``ok`` keeps describing the
    architecture.
    """
    violation = ArchitectureViolation(
        rule_id="HEC001",
        importer="pkg.domain.model",
        imported="pkg.adapters.db",
        importer_group="domain",
        imported_group="adapter",
        source_path=tmp_path / "pkg/domain/model.py",
        line=1,
    )
    result = ArchitectureCheckResult(violations=(violation,), passed=True)

    output = render_text(result)
    payload = json.loads(render_json(result))

    assert "architecture check passed" in output, (
        f"expected passed=True to show the pass notice, got {output!r}"
    )
    assert payload["ok"] is False, (
        f"ok must keep describing the architecture, got {payload!r}"
    )
    assert payload["status"] == "passed", (
        f"expected passed=True to report success, got {payload!r}"
    )
