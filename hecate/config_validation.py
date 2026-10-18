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
            f"remove the duplicate prefix {shadow.shadowed_prefix!r} from "
            f"later group {shadow.shadowed_group!r}, or remove every earlier "
            f"prefix that contains {shadow.shadowed_prefix!r}"
        )
    return (
        f"place group {shadow.shadowed_group!r} before group "
        f"{shadow.winning_group!r} and every other earlier group with a "
        f"prefix that contains {shadow.shadowed_prefix!r} to make the narrower "
        f"classification effective, remove the unreachable prefix "
        f"{shadow.shadowed_prefix!r} from group {shadow.shadowed_group!r}, "
        f"remove every earlier prefix that contains "
        f"{shadow.shadowed_prefix!r}, or move it to the group that should own it"
    )
