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
from .imports import compute_module_name
from .policy import UNCLASSIFIED_MODULE_MODES, ArchitecturePolicy

if typ.TYPE_CHECKING:
    from .config import PackageRoot


def collect_unclassified_modules(
    package_root: PackageRoot,
    *,
    policy: ArchitecturePolicy,
    report: dict[str, UnclassifiedModuleDiagnostic],
) -> None:
    """Record the modules under ``package_root`` that ``policy`` does not claim.

    A module is named whether or not it imports anything, so a package added
    without a matching prefix is visible on its first run rather than on its
    first forbidden import.

    The mode is read here rather than by the caller so the default traversal
    stays a single loop: under ``ignore`` this is the only work the pass does.

    The first source path wins when two roots supply the same module name, so
    the reported location does not depend on the order roots are declared in.
    """
    mode = policy.unclassified_modules
    if mode not in UNCLASSIFIED_MODULE_MODES or mode == "ignore":
        return
    severity = unclassified_module_severity(mode)
    for source_path in sorted(package_root.root.rglob("*.py")):
        module = compute_module_name(package_root.root, package_root.name, source_path)
        if policy.group_for(module) is not None:
            continue
        report.setdefault(
            module,
            UnclassifiedModuleDiagnostic(
                module=module, source_path=source_path, severity=severity
            ),
        )
