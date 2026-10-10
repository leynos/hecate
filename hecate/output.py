"""Text and JSON output rendering."""

from __future__ import annotations

import json
import typing as typ

from .checker import ArchitectureCheckResult

if typ.TYPE_CHECKING:
    import collections.abc as cabc


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
    lines = [
        *(violation.render() for violation in result.violations),
        *(failure.render() for failure in result.coverage_failures),
    ]
    if show_ignored:
        lines.extend(ignored.render() for ignored in result.ignored)
    if show_coverage:
        lines.extend(_coverage_warning_lines(result))
    return "\n".join(_with_pass_notice(lines, ok=result.ok)) + "\n"


def _coverage_warning_lines(result: ArchitectureCheckResult) -> cabc.Iterator[str]:
    """Yield rendered coverage entries that do not already fail the check."""
    return (
        diagnostic.render()
        for diagnostic in result.coverage
        if not diagnostic.is_failure
    )


def _with_pass_notice(lines: list[str], *, ok: bool) -> list[str]:
    """Return ``lines`` prefixed with the pass notice when the check passed.

    The notice leads the output so a passing run is the first thing a reader
    or a snapshot sees, rather than trailing a list of diagnostics.
    """
    if not ok:
        return lines
    return ["hecate: architecture check passed", *lines]


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
