"""Renderer tests for unclassified-module diagnostics.

These live apart from the edge-diagnostic renderer tests in ``test_output``
because the unclassified section has its own visibility rule: the configured
mode, not a command-line flag, decides whether it is reported.
"""

from __future__ import annotations

import json
from pathlib import Path

from hecate.checker import ArchitectureCheckResult
from hecate.diagnostics import UnclassifiedModuleDiagnostic
from hecate.output import render_json, render_text
from hecate.policy import Severity


def _unclassified(
    tmp_path: Path, *, severity: Severity, module: str = "pkg.newfeature"
) -> UnclassifiedModuleDiagnostic:
    """Build one unclassified-module diagnostic for rendering tests."""
    return UnclassifiedModuleDiagnostic(
        module=module,
        source_path=tmp_path.joinpath(*module.split("."), "__init__.py"),
        severity=severity,
    )


def test_text_always_renders_unclassified_modules(tmp_path: Path) -> None:
    """A configured mode is not gated behind a flag.

    ``warn`` and ``error`` exist to make a coverage gap visible, so the text
    renderer shows what they found without being asked; the mode itself was the
    request.
    """
    diagnostic = _unclassified(tmp_path, severity=Severity.WARNING)
    result = ArchitectureCheckResult(violations=(), unclassified_modules=(diagnostic,))

    output = render_text(result)

    assert "HEC002 warning pkg.newfeature" in output, (
        f"expected the warning in text output, got {output!r}"
    )
    assert "no architecture group matched this module" in output, (
        f"expected the coverage message, got {output!r}"
    )
    assert output.endswith("\n"), f"expected a trailing newline, got {output!r}"


def test_text_reports_a_warning_only_run_as_passed(tmp_path: Path) -> None:
    """Warnings are reported and still exit 0, so the pass line stays."""
    diagnostic = _unclassified(tmp_path, severity=Severity.WARNING)
    result = ArchitectureCheckResult(violations=(), unclassified_modules=(diagnostic,))

    output = render_text(result)

    assert result.ok, f"a warning must not fail the check, got {result!r}"
    assert output.startswith("hecate: architecture check passed\n"), (
        f"expected the pass notice to lead, got {output!r}"
    )


def test_unclassified_error_suppresses_the_pass_notice(tmp_path: Path) -> None:
    """An error-severity finding clears ``ok`` and with it the pass line."""
    diagnostic = _unclassified(tmp_path, severity=Severity.ERROR)
    result = ArchitectureCheckResult(violations=(), unclassified_modules=(diagnostic,))

    output = render_text(result)

    assert not result.ok, f"an error severity must fail the check, got {result!r}"
    assert "architecture check passed" not in output, (
        f"a failing run must not claim success, got {output!r}"
    )


def test_json_omits_unclassified_modules_by_default(tmp_path: Path) -> None:
    """The default payload gains no key, so existing consumers are unaffected."""
    diagnostic = _unclassified(tmp_path, severity=Severity.WARNING)
    result = ArchitectureCheckResult(violations=(), unclassified_modules=(diagnostic,))

    payload = json.loads(render_json(result))

    assert "unclassified_modules" not in payload, (
        f"a suppressed section must be absent, not empty: {payload!r}"
    )


def test_json_serializes_an_unclassified_module(tmp_path: Path) -> None:
    """With the section included, every field survives serialization."""
    diagnostic = _unclassified(tmp_path, severity=Severity.ERROR)
    result = ArchitectureCheckResult(violations=(), unclassified_modules=(diagnostic,))

    payload = json.loads(render_json(result, include_unclassified=True))
    entry = payload["unclassified_modules"][0]

    assert entry == {
        "rule_id": "HEC002",
        "severity": "error",
        "module": "pkg.newfeature",
        "source_path": str(tmp_path / "pkg/newfeature/__init__.py"),
        "message": "no architecture group matched this module",
    }, f"expected the full module identity, got {entry!r}"
    assert payload["ok"] is False, (
        f"an error-severity finding must clear ok, got {payload!r}"
    )


def test_json_reports_an_empty_unclassified_section_when_included(
    tmp_path: Path,
) -> None:
    """Included and empty is a different claim from absent.

    A consumer reading an empty array learns the tree was fully classified;
    a consumer reading no key at all learns nothing was evaluated.
    """
    result = ArchitectureCheckResult(violations=())

    payload = json.loads(render_json(result, include_unclassified=True))

    assert payload["unclassified_modules"] == [], (
        f"expected an empty evaluated list, got {payload!r}"
    )
    assert payload["ok"] is True, f"expected a passing payload, got {payload!r}"
