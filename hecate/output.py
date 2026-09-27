"""Text and JSON output rendering."""

from __future__ import annotations

import json

from .checker import ArchitectureCheckResult


def render_text(
    result: ArchitectureCheckResult,
    *,
    show_ignored: bool = False,
    show_coverage: bool = False,
) -> str:
    """Render deterministic plain text for CI and snapshots.

    Violations and coverage failures are always shown, because both change the
    exit code. Coverage warnings stay behind ``--show-coverage`` so that
    non-strict runs keep their existing output shape.
    """
    lines = [violation.render() for violation in result.violations]
    lines.extend(failure.render() for failure in result.coverage_failures)
    if show_ignored and result.ignored:
        lines.extend(ignored.render() for ignored in result.ignored)
    if show_coverage:
        lines.extend(
            diagnostic.render()
            for diagnostic in result.coverage
            if not diagnostic.is_failure
        )
    if result.ok:
        lines.insert(0, "hecate: architecture check passed")
    return "\n".join(lines) + "\n"


def render_json(
    result: ArchitectureCheckResult,
    *,
    show_ignored: bool = False,
    show_coverage: bool = True,
) -> str:
    """Render deterministic JSON output."""
    payload: dict[str, object] = {
        "ok": result.ok,
        "violations": [violation.to_dict() for violation in result.violations],
    }
    if show_coverage:
        payload["coverage"] = [diagnostic.to_dict() for diagnostic in result.coverage]
    if show_ignored:
        payload["ignored"] = [ignored.to_dict() for ignored in result.ignored]
    return f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
