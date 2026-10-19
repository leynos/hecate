"""Public-surface tests for the diagnostic renderers.

These live apart from the per-diagnostic rendering tests because they pin the
call contract rather than a rendering rule: the keyword-only parameters both
renderers shipped before warning support, the explicit command outcome they
now accept, and the contradiction they refuse to render.
"""

from __future__ import annotations

import json
import typing as typ
from pathlib import Path

import pytest

from hecate.checker import ArchitectureCheckResult
from hecate.diagnostics import (
    ArchitectureViolation,
    ArchitectureWarning,
    CoverageDiagnostic,
    IgnoredImportDiagnostic,
)
from hecate.output import render_json, render_text
from hecate.policy import EdgeState, Severity

if typ.TYPE_CHECKING:
    import collections.abc as cabc


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


def test_renderers_take_the_command_outcome_explicitly(tmp_path: Path) -> None:
    """``passed`` overrides the architecture outcome in both formats.

    The CLI owns the exit-code decision and states it to the renderer, so a
    warning-only run failed by ``--fail-on-warnings`` shows no pass notice
    while ``ok`` keeps describing the architecture. The outcome is a
    keyword-only argument, so the pre-warning call surface still works.
    """
    warning = ArchitectureWarning(
        rule_id="HEC001",
        importer="pkg.application.service",
        imported="pkg.adapters.db",
        importer_group="application",
        imported_group="adapter",
        source_path=tmp_path / "pkg/application/service.py",
        line=7,
    )
    result = ArchitectureCheckResult(violations=(), warnings=(warning,))

    output = render_text(result, passed=False)
    payload = json.loads(render_json(result, passed=False))

    assert "architecture check passed" not in output, (
        f"expected passed=False to suppress the pass notice, got {output!r}"
    )
    assert payload["ok"] is True, (
        f"ok must keep describing the architecture, got {payload!r}"
    )
    assert payload["status"] == "failed", (
        f"expected passed=False to report failure, got {payload!r}"
    )


def test_renderers_fall_back_to_the_architecture_outcome(tmp_path: Path) -> None:
    """Omitting ``passed`` states no command policy.

    A renderer called without the outcome has no enforcement decision to
    report, so it must describe the architecture result rather than invent a
    command status.
    """
    warning = ArchitectureWarning(
        rule_id="HEC001",
        importer="pkg.application.service",
        imported="pkg.adapters.db",
        importer_group="application",
        imported_group="adapter",
        source_path=tmp_path / "pkg/application/service.py",
        line=7,
    )
    result = ArchitectureCheckResult(violations=(), warnings=(warning,))

    output = render_text(result)
    payload = json.loads(render_json(result))

    assert output.startswith("hecate: architecture check passed\n"), (
        f"the architecture result governs when no policy is stated, got {output!r}"
    )
    assert payload["status"] == "passed", (
        f"status must follow the architecture result, got {payload!r}"
    )


@pytest.mark.parametrize(
    "render",
    [render_text, render_json],
    ids=["text", "json"],
)
def test_renderers_reject_an_unknown_keyword(
    render: cabc.Callable[..., str],
) -> None:
    """A misspelled option fails instead of silently doing nothing.

    Accepting ``**options`` turns the named parameters into a mapping, so
    without an explicit check an unknown keyword would be dropped and the
    caller would receive default output while believing the option applied.
    """
    result = ArchitectureCheckResult(violations=())

    with pytest.raises(TypeError, match="show_coverge"):
        render(result, show_coverge=True)


@pytest.mark.parametrize(
    "render",
    [render_text, render_json],
    ids=["text", "json"],
)
def test_renderers_reject_a_contradicted_pass_claim(
    tmp_path: Path, render: cabc.Callable[..., str]
) -> None:
    """A pass claim the result contradicts is refused, not rendered.

    A violation always fails the architecture result, so no command policy can
    turn it green. Rendering it as passed would produce output that disagrees
    with its own diagnostics, which is the failure mode an explicit outcome is
    meant to prevent; the boundary refuses it instead.
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
    result = ArchitectureCheckResult(violations=(violation,))

    with pytest.raises(ValueError, match="contradicts"):
        render(result, passed=True)
