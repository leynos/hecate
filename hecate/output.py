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
    passed: bool | None = None,
) -> str:
    """Render deterministic plain text for CI and snapshots.

    Violations, error-severity coverage findings, and warning-level edges are
    always shown, because each either changes the exit code or is a dependency
    the policy wants kept visible while it migrates. Warning coverage findings
    stay behind ``--show-coverage`` so that non-strict runs keep their existing
    output shape.

    Unclassified-module diagnostics are the exception: a mode that was asked
    for by configuration is always shown. ``warn`` and ``error`` both exist to
    make a policy coverage gap visible, so a mode that reported nothing until a
    flag was passed would defeat the setting. Under ``ignore`` there is nothing
    to show and the default output is unchanged.

    ``passed`` is the command outcome, decided by the caller from the same
    policy that produces the exit code. A caller that supplies it states the
    outcome explicitly; a caller that omits it gets the architecture result's
    own outcome, which is the right answer when no enforcement policy is in
    force. A pass claim the result contradicts raises :class:`ValueError`
    rather than rendering output that disagrees with its own diagnostics.
    """
    lines = [*_always_rendered_lines(result)]
    if show_ignored:
        lines.extend(ignored.render() for ignored in result.ignored)
    if show_coverage:
        lines.extend(_coverage_warning_lines(result))
    outcome = _resolve_outcome(result, passed=passed)
    return "\n".join(_with_pass_notice(lines, ok=outcome)) + "\n"


def _resolve_outcome(result: ArchitectureCheckResult, *, passed: bool | None) -> bool:
    """Return the command outcome, refusing a contradicted pass claim.

    ``None`` means the caller states no command policy, so the architecture
    result's own outcome governs. An explicit ``True`` must agree with it: the
    command outcome can differ from ``ok`` by failing a passing result under
    ``--fail-on-warnings``, never by passing one that has violations or
    error-severity diagnostics.
    """
    if passed is None:
        return result.ok
    if passed and not result.ok:
        msg = (
            "passed=True contradicts an architecture result that did not pass; "
            "render the result's own outcome instead"
        )
        raise ValueError(msg)
    return passed


def _always_rendered_lines(result: ArchitectureCheckResult) -> cabc.Iterator[str]:
    """Yield the diagnostics every text run reports, whatever the flags.

    Each either changes the exit code or is something the policy asked to keep
    visible, so none of them may depend on a display option.
    """
    yield from (violation.render() for violation in result.violations)
    yield from (failure.render() for failure in result.coverage_failures)
    yield from (diagnostic.render() for diagnostic in result.unclassified_modules)
    yield from (warning.render() for warning in result.warnings)


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


# Every option here is part of the renderer's published keyword surface, and
# ``passed`` had to join them rather than ride on the architecture result, so
# the count is deliberate. Collapsing the flags would break existing callers.
# pylint: disable-next=too-many-arguments
def render_json(
    result: ArchitectureCheckResult,
    *,
    show_ignored: bool = False,
    show_coverage: bool = True,
    include_unclassified: bool = False,
    passed: bool | None = None,
) -> str:
    """Render deterministic JSON output.

    The ``warnings`` list is always present, even when empty: warning-level
    edges are visible in every run by design, so a consumer can read the key
    unconditionally rather than inferring its absence from the flags.

    ``include_unclassified`` follows the ``show_ignored`` pattern: the section
    is present, and empty, whenever the mode can produce entries, so a consumer
    reads an empty array as "evaluated and fully classified" rather than as
    "not reported". Under ``ignore`` the section is absent entirely and the
    default payload is unchanged.

    ``ok`` reports the architecture result and deliberately ignores warnings,
    so it cannot double as the command outcome once ``--fail-on-warnings`` can
    fail a run it calls ``ok``. ``status`` carries the command outcome from
    ``passed`` instead, which keeps the existing ``ok`` meaning intact for
    current consumers. Omitting ``passed`` states no command policy, so
    ``status`` falls back to the architecture outcome; a pass claim the result
    contradicts raises :class:`ValueError`.
    """
    payload: dict[str, object] = {
        "ok": result.ok,
        "status": "passed" if _resolve_outcome(result, passed=passed) else "failed",
        "violations": [violation.to_dict() for violation in result.violations],
        "warnings": [warning.to_dict() for warning in result.warnings],
    }
    payload.update(
        _optional_json_sections(
            result,
            show_ignored=show_ignored,
            show_coverage=show_coverage,
            include_unclassified=include_unclassified,
        )
    )
    return f"{json.dumps(payload, indent=2, sort_keys=True)}\n"


def _optional_json_sections(
    result: ArchitectureCheckResult,
    *,
    show_ignored: bool,
    show_coverage: bool,
    include_unclassified: bool,
) -> dict[str, object]:
    """Return the JSON sections this run was asked to report.

    An omitted key and an empty list make different claims, so a suppressed
    section is left out entirely rather than serialized empty.
    """
    sections: dict[str, object] = {}
    if show_coverage:
        sections["coverage"] = [diagnostic.to_dict() for diagnostic in result.coverage]
    if show_ignored:
        sections["ignored"] = [ignored.to_dict() for ignored in result.ignored]
    if include_unclassified:
        sections["unclassified_modules"] = [
            diagnostic.to_dict() for diagnostic in result.unclassified_modules
        ]
    return sections
