"""Build deterministic diagnostics for shadowed group prefixes.

The configuration loader owns the validation rule; this module only formats
the path-qualified messages shown when a policy contains unreachable prefixes.
"""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

    from .policy import ShadowedPrefix


def _shadowed_prefix_diagnostics(
    shadows: tuple[ShadowedPrefix, ...], path: Path
) -> tuple[str, ...]:
    """Return one ordered, path-qualified diagnostic for each shadow."""
    return tuple(
        f"{path}: tool.hecate.groups: prefix {shadow.shadowed_prefix!r} in "
        f"group {shadow.shadowed_group!r} is shadowed by earlier prefix "
        f"{shadow.winning_prefix!r} in group {shadow.winning_group!r}; "
        f"{_shadowed_prefix_remedy(shadow)}"
        for shadow in shadows
    )


def _shadowed_prefix_remedy(shadow: ShadowedPrefix) -> str:
    """Describe how to repair one shadowed prefix diagnostic."""
    if shadow.shadowed_prefix == shadow.winning_prefix:
        return (
            f"remove the duplicate prefix from group {shadow.shadowed_group!r} "
            f"or group {shadow.winning_group!r}"
        )
    return (
        f"place group {shadow.shadowed_group!r} before group "
        f"{shadow.winning_group!r} to make the narrower "
        "classification effective, remove the unreachable prefix, or move it "
        "to the group that should own it"
    )
