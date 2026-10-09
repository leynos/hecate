"""Symbol-origin provenance over the analysed module namespace model.

:mod:`hecate.namespaces` records what each module binds and which modules it
pulls in with ``from origin import *``. This module resolves those raw facts
into provenance:

* :meth:`OriginIndex.origins_for` maps one import target written in source code
  to every module that plausibly supplies it, following re-export chains; and
* :meth:`OriginIndex.wildcard_exports` lists the concrete origins a
  ``from module import *`` statement would bind.

The two views are deliberately separate. ``__all__`` governs only the wildcard
view, so the binding view stays complete and an explicitly imported re-export
keeps its origin even when ``__all__`` omits it.

Targets that cannot be resolved are classified by :meth:`OriginIndex.resolve`
rather than dropped, so policy evaluation can distinguish "no dependency exists"
from "Hecate could not tell".
"""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

from .namespaces import Binding, Definition, Imported, ModuleNamespace

if typ.TYPE_CHECKING:
    from .config import PackageRoot

#: Separator between a module name and a symbol looked up inside that module.
SYMBOL_SEPARATOR = "."


class Resolution(enum.StrEnum):
    """How well an import target could be resolved."""

    RESOLVED = "resolved"
    """The target names a scanned module, or a symbol some scanned module binds."""

    UNRESOLVED_INTERNAL = "unresolved_internal"
    """The target sits under a package root but no analysed module supplies it."""

    EXTERNAL = "external"
    """The target sits outside every scanned package root."""


@dc.dataclass(frozen=True, slots=True)
class OriginIndex:
    """Resolved symbol provenance for the scanned package roots."""

    namespaces: dict[str, ModuleNamespace]
    package_names: tuple[str, ...]

    def is_internal(self, target: str) -> bool:
        """Return whether ``target`` names or sits under a package root."""
        return any(
            target == package or target.startswith(f"{package}{SYMBOL_SEPARATOR}")
            for package in self.package_names
        )

    def resolve(self, target: str) -> Resolution:
        """Classify how far ``target`` could be resolved.

        A target resolves when it names a scanned module, or a symbol that some
        scanned module actually binds. Anything else is either an external
        dependency or an internal import Hecate failed to explain.
        """
        if target in self.namespaces:
            return Resolution.RESOLVED
        if SYMBOL_SEPARATOR in target:
            module, symbol = _split_symbol(target)
            if module in self.namespaces and self._symbol_origins(
                module, symbol, seen=frozenset()
            ):
                return Resolution.RESOLVED
        if self.is_internal(target):
            return Resolution.UNRESOLVED_INTERNAL
        return Resolution.EXTERNAL

    def origins_for(self, target: str) -> tuple[str, ...]:
        """Return every origin one written import target could refer to.

        The target itself always comes first, so callers that only need the
        module-level edge still see it; the remaining entries come from the
        re-export chains that supply the target's name.
        """
        origins = [target]
        if SYMBOL_SEPARATOR in target:
            module, symbol = _split_symbol(target)
            if module in self.namespaces:
                origins.extend(self._symbol_origins(module, symbol, seen=frozenset()))
        return tuple(dict.fromkeys(origins))

    def wildcard_exports(self, module: str) -> tuple[str, ...]:
        """Return the origins a ``from module import *`` statement would bind.

        Returns an empty tuple when the module is unknown or its ``__all__``
        selects nothing, which is the correct answer for ``__all__ = []``.
        """
        if module not in self.namespaces:
            return ()
        origins: list[str] = []
        for name in sorted(self._export_names(module, seen=frozenset())):
            origins.extend(self._symbol_origins(module, name, seen=frozenset()))
        origins.extend(self._opaque_wildcard_origins(module, seen=frozenset()))
        return tuple(dict.fromkeys(origins))

    def _effective_binding(self, module: str, symbol: str) -> Binding | None:
        """Return how ``symbol`` is supplied on ``module``, if it is at all.

        A name bound directly on the module wins. Otherwise the name may arrive
        through ``from origin import *``, in which case the supplying module is
        recorded as its origin so provenance keeps flowing.
        """
        namespace = self.namespaces[module]
        binding = namespace.binding_map.get(symbol)
        if binding is not None:
            return binding
        for wildcard_origin in namespace.wildcard_origins:
            if symbol in self._export_names(wildcard_origin, seen=frozenset()):
                return Imported(origin=wildcard_origin, symbol=symbol)
        return None

    def _export_names(self, module: str, *, seen: frozenset[str]) -> frozenset[str]:
        """Return the names ``from module import *`` would bind."""
        if module in seen or module not in self.namespaces:
            return frozenset()
        namespace = self.namespaces[module]
        if namespace.has_explicit_all:
            return frozenset(namespace.all_names or ())
        names = {name for name, _ in namespace.bindings if not name.startswith("_")}
        next_seen = seen | {module}
        for wildcard_origin in namespace.wildcard_origins:
            names |= self._export_names(wildcard_origin, seen=next_seen)
        return frozenset(names)

    def _symbol_origins(
        self, module: str, symbol: str, *, seen: frozenset[str]
    ) -> tuple[str, ...]:
        """Return the provenance chain for the qualified name ``module.symbol``.

        The chain leads with ``module.symbol`` itself, matching the qualified
        names Hecate reports, and then follows re-exports towards the module
        that actually defines the name.
        """
        qualified = f"{module}{SYMBOL_SEPARATOR}{symbol}"
        return tuple(dict.fromkeys(self._walk_symbol(qualified, seen=seen)))

    def _walk_symbol(self, qualified: str, *, seen: frozenset[str]) -> list[str]:
        if qualified in seen:
            return []
        next_seen = seen | {qualified}
        module, symbol = _split_symbol(qualified)
        # A qualified name that is itself a scanned module is the origin, and a
        # name whose module Hecate never analysed has nothing deeper to follow.
        if qualified in self.namespaces or module not in self.namespaces:
            return [qualified]
        binding = self._effective_binding(module, symbol)
        if binding is None:
            return []
        if isinstance(binding, Definition):
            return [qualified]
        if binding.symbol is None:
            # ``import a.b`` binds the module itself, not one of its attributes.
            return [qualified, binding.origin]
        child = f"{binding.origin}{SYMBOL_SEPARATOR}{binding.symbol}"
        return [qualified, *self._walk_symbol(child, seen=next_seen)]

    def _opaque_wildcard_origins(
        self, module: str, *, seen: frozenset[str]
    ) -> tuple[str, ...]:
        """Return wildcard sources whose export set Hecate cannot enumerate.

        A literal ``__all__`` replaces the wildcard export set outright, so the
        star imports contribute nothing and are not reported.
        """
        if module in seen:
            return ()
        namespace = self.namespaces.get(module)
        if namespace is None:
            return (module,)
        if namespace.has_explicit_all:
            return ()
        next_seen = seen | {module}
        origins: list[str] = []
        for wildcard_origin in namespace.wildcard_origins:
            origins.extend(
                self._opaque_wildcard_origins(wildcard_origin, seen=next_seen)
            )
        return tuple(origins)


def _split_symbol(qualified: str) -> tuple[str, str]:
    """Split a qualified name into its module and symbol parts."""
    module, _, symbol = qualified.rpartition(SYMBOL_SEPARATOR)
    return module, symbol


def build_origin_index(
    packages: tuple[PackageRoot, ...],
    namespaces: dict[str, ModuleNamespace],
) -> OriginIndex:
    """Build an :class:`OriginIndex` over already-analysed namespaces."""
    return OriginIndex(
        namespaces=namespaces,
        package_names=tuple(item.name for item in packages),
    )
