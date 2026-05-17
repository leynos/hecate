"""Text and JSON output rendering."""

from __future__ import annotations

import json

from .checker import ArchitectureCheckResult


def render_text(result: ArchitectureCheckResult, *, show_ignored: bool = False) -> str:
    """Render deterministic plain text for CI and snapshots."""
    if result.ok:
        lines = ["hecate: architecture check passed"]
    else:
        lines = [violation.render() for violation in result.violations]
    if show_ignored and result.ignored:
        lines.extend(ignored.render() for ignored in result.ignored)
    return "\n".join(lines) + "\n"


def render_json(result: ArchitectureCheckResult, *, show_ignored: bool = False) -> str:
    """Render deterministic JSON output."""
    payload: dict[str, object] = {
        "ok": result.ok,
        "violations": [violation.to_dict() for violation in result.violations],
    }
    if show_ignored:
        payload["ignored"] = [ignored.to_dict() for ignored in result.ignored]
    return f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
