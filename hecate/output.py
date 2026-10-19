"""Text and JSON output rendering."""

from __future__ import annotations

import json
import typing as typ

from .checker import ArchitectureCheckResult
from .diagnostics import fails_check

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def render_text(
    result: ArchitectureCheckResult,
    *,
    show_ignored: bool = False,
    show_coverage: bool = False,
) -> str:
    """Render deterministic plain text for CI and snapshots.

    Violations and error-severity coverage findings are always shown, because
    both change the exit code. Warning coverage findings stay behind
    ``--show-coverage`` so that non-strict runs keep their existing output
    shape.

    Unclassified-module diagnostics are the exception: a mode that was asked
    for by configuration is always shown. ``warn`` and ``error`` both exist to
    make a policy coverage gap visible, so a mode that reported nothing until a
    flag was passed would defeat the setting. Under ``ignore`` there is nothing
    to show and the default output is unchanged.
    """
    lines = [
        *(violation.render() for violation in result.violations),
        *(failure.render() for failure in result.coverage_failures),
        *(diagnostic.render() for diagnostic in result.unclassified_modules),
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
        if not fails_check(diagnostic.severity)
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
    include_unclassified: bool = False,
) -> str:
    """Render deterministic JSON output.

    ``include_unclassified`` follows the ``show_ignored`` pattern: the section
    is present, and empty, whenever the mode can produce entries, so a consumer
    reads an empty array as "evaluated and fully classified" rather than as
    "not reported". Under ``ignore`` the section is absent entirely and the
    default payload is unchanged.
    """
    payload: dict[str, object] = {
        "ok": result.ok,
        "violations": [violation.to_dict() for violation in result.violations],
    }
    if show_coverage:
        payload["coverage"] = [diagnostic.to_dict() for diagnostic in result.coverage]
    if show_ignored:
        payload["ignored"] = [ignored.to_dict() for ignored in result.ignored]
    if include_unclassified:
        payload["unclassified_modules"] = [
            diagnostic.to_dict() for diagnostic in result.unclassified_modules
        ]
    return f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
