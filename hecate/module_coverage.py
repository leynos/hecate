"""The module pass: which discovered modules a policy claims.

Coverage of the *graph* and coverage of the *policy* are different questions.
An edge is checked only when both endpoints classify, so a module sitting
outside every group is enforced over nothing, and its imports bypass the policy
until an edge's other endpoint happens to expose it. This pass answers the
policy question directly: for every ``*.py`` file beneath a configured package
root, is some group responsible for it?
"""

from __future__ import annotations

import typing as typ

from .diagnostics import UnclassifiedModuleDiagnostic, unclassified_module_severity
from .policy import UNCLASSIFIED_MODULE_MODES, ArchitecturePolicy

if typ.TYPE_CHECKING:
    from .imports import DiscoveredModule


def collect_unclassified_modules(
    discovered: tuple[DiscoveredModule, ...],
    *,
    policy: ArchitecturePolicy,
    report: dict[str, UnclassifiedModuleDiagnostic],
) -> None:
    """Record the modules in ``discovered`` that ``policy`` does not claim.

    A module is named whether or not it imports anything, so a package added
    without a matching prefix is visible on its first run rather than on its
    first forbidden import.

    The mode is read here rather than by the caller so the default traversal
    stays a single loop: under ``ignore`` this is the only work the pass does.

    When two roots supply the same module name, the first root declared in the
    configuration wins, because the caller walks ``config.packages`` in order
    and the report keeps the first record for a name. Declaration order is the
    tie-break for the same reason group matching is ordered: a reader who
    ordered the configuration should be able to predict which one applies.
    """
    mode = policy.unclassified_modules
    if mode not in UNCLASSIFIED_MODULE_MODES or mode == "ignore":
        return
    severity = unclassified_module_severity(mode)
    for source in discovered:
        if policy.group_for(source.module) is not None:
            continue
        report.setdefault(
            source.module,
            UnclassifiedModuleDiagnostic(
                module=source.module,
                source_path=source.source_path,
                severity=severity,
            ),
        )
