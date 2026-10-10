"""Property tests for origin resolution over generated re-export chains.

Complements the example-based tests in :mod:`tests.test_reexports`. The
examples pin individual rules; the properties here assert the invariants that
must hold over every generated graph, which is where a subtle traversal or
cycle-guard change shows up first.

The edge-outcome totality properties live in
:mod:`tests.test_origin_totality`.
"""

from __future__ import annotations

import collections.abc as cabc
import contextlib
import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from hecate.config import PackageRoot
from hecate.namespaces import analyse_namespaces
from hecate.origins import OriginIndex, Resolution, build_origin_index

#: How one module in a generated chain reaches the next.
_CHAIN_LINK = st.sampled_from(("named", "visible", "hidden"))


def _write_chain(
    root: Path, links: list[str], *, is_cyclic: bool
) -> tuple[PackageRoot, ...]:
    """Write a package whose modules form one re-export chain.

    ``links[i]`` decides how ``m<i>`` reaches the ``Thing`` defined in the last
    module. The three spellings cover the cases the origin walk has to keep
    apart: a named import, a wildcard whose ``__all__`` selects the name, and a
    wildcard whose ``__all__`` deliberately withholds it. ``is_cyclic`` adds a
    wildcard back-edge from the defining module to the first one, so the graph
    stops being a chain and the cycle guards are exercised.
    """
    files = {
        "__init__.py": "from .barrel import *\n",
        "barrel.py": "from .m0 import *\n__all__ = ['Thing']\n",
    }
    last = len(links)
    for position in range(last + 1):
        name = f"m{position}.py"
        if position == last:
            body = "class Thing: ...\n"
            files[name] = body + ("from .m0 import *\n" if is_cyclic else "")
        elif links[position] == "named":
            files[name] = f"from .m{position + 1} import Thing\n"
        elif links[position] == "visible":
            files[name] = f"from .m{position + 1} import *\n__all__ = ['Thing']\n"
        else:
            files[name] = (
                f"from .m{position + 1} import *\n"
                "class Other: ...\n"
                "__all__ = ['Other']\n"
            )
    package_root = root / "pkg"
    for relative_path, contents in files.items():
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return (PackageRoot("pkg", package_root),)


@contextlib.contextmanager
def _chain_index(links: list[str], *, is_cyclic: bool) -> cabc.Iterator[OriginIndex]:
    """Build a generated chain in a throwaway directory and yield its index.

    Each generated input gets its own directory. Sharing one across inputs
    would leave a longer chain's modules behind as inert files in the package,
    and the property would then be measuring the leftover state as much as the
    graph it generated.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        packages = _write_chain(Path(tmp_dir), links, is_cyclic=is_cyclic)
        yield build_origin_index(packages, analyse_namespaces(packages))


def _chain_supplies(links: list[str]) -> list[bool]:
    """Return, for each module, whether the name is supplied on it at all.

    This is the independent reference fold the chain properties compare
    against. It restates the two rules that matter in a few lines: a ``named``
    link binds ``Thing`` outright, because an explicit import never consults
    ``__all__``; a wildcard link binds it only when the module it draws from
    exports it; and a ``hidden`` wildcard withholds it from everyone above.
    Keeping the reference separate from the analyser is the point: a change
    that makes the production walk disagree with this fold fails here rather
    than passing because both sides were edited together.
    """
    last = len(links)
    supplies = [False] * (last + 1)
    exports = [True] * (last + 1)
    supplies[last] = True
    for position in range(last - 1, -1, -1):
        supplies[position] = links[position] == "named" or exports[position + 1]
        exports[position] = links[position] != "hidden"
    return supplies


def _chain_origins(links: list[str]) -> tuple[str, ...]:
    """Return the origin tuple the analyser must record for a generated chain.

    ``origins_for`` always leads with the written target, because that is the
    module the import statement names. Each following module appears only when
    the walk both reaches it and finds the name supplied there, and reaching it
    requires every earlier hop to supply the name as well. Over a single chain
    that reduces to the longest prefix of supplying modules.
    """
    supplies = _chain_supplies(links)
    origins = ["pkg.m0.Thing"]
    position = 1
    while position < len(supplies) and all(supplies[: position + 1]):
        origins.append(f"pkg.m{position}.Thing")
        position += 1
    return tuple(origins)


@given(st.lists(_CHAIN_LINK, max_size=4), st.booleans())
def test_origin_resolution_is_deterministic_and_cycle_safe(
    links: list[str], is_cyclic: bool
) -> None:
    """Solving the same generated graph twice yields the same origins.

    Origin resolution walks wildcard chains and branches over every binding a
    name may have, so a careless implementation can depend on traversal order
    or fail to terminate when two modules re-export each other. Resolving twice
    over one index catches order dependence; comparing the chains against the
    same graph plus a back-edge catches a walk that only works on a tree.
    """
    with _chain_index(links, is_cyclic=is_cyclic) as index:
        first = index.origins_for("pkg.m0.Thing")
        second = index.origins_for("pkg.m0.Thing")
        resolution = index.resolve("pkg.m0.Thing")

    assert first == second, (
        f"origin resolution must be deterministic, got {first!r} then {second!r}"
    )
    assert len(set(first)) == len(first), (
        f"origins must not repeat for chain {links!r} (cyclic={is_cyclic}): {first!r}"
    )
    assert first[0] == "pkg.m0.Thing", (
        f"the written target must lead its own origins, got {first!r}"
    )
    assert resolution is index.resolve("pkg.m0.Thing"), (
        f"resolution must not depend on how often it is asked: {resolution!r}"
    )


@given(st.lists(_CHAIN_LINK, max_size=4))
def test_a_back_edge_does_not_change_what_the_name_resolves_to(
    links: list[str],
) -> None:
    """Adding a re-export cycle leaves the observable provenance unchanged.

    A cycle guard that dropped origins or stopped the walk early would make the
    answer depend on whether a back-edge happens to exist, which is an accident
    of module layout rather than of what the code re-exports. The exotic graph
    must resolve exactly like the acyclic one, in both directions: no origin
    gained and none lost.
    """
    with _chain_index(links, is_cyclic=False) as acyclic:
        plain_origins = acyclic.origins_for("pkg.m0.Thing")
        plain_resolution = acyclic.resolve("pkg.m0.Thing")
        plain_exports = acyclic.wildcard_exports("pkg")
    with _chain_index(links, is_cyclic=True) as cyclic:
        back_edge_origins = cyclic.origins_for("pkg.m0.Thing")
        back_edge_resolution = cyclic.resolve("pkg.m0.Thing")
        back_edge_exports = cyclic.wildcard_exports("pkg")

    assert back_edge_origins == plain_origins, (
        f"a back-edge changed the provenance for chain {links!r}: "
        f"{back_edge_origins!r} vs {plain_origins!r}"
    )
    assert back_edge_resolution is plain_resolution, (
        f"a back-edge changed the resolution for chain {links!r}: "
        f"{back_edge_resolution!r} vs {plain_resolution!r}"
    )
    assert back_edge_exports == plain_exports, (
        f"a back-edge changed the export set for chain {links!r}: "
        f"{back_edge_exports!r} vs {plain_exports!r}"
    )


@given(st.lists(_CHAIN_LINK, max_size=4), st.booleans())
def test_wildcard_visibility_follows_the_chain(
    links: list[str], is_cyclic: bool
) -> None:
    """A wildcard consumer sees a name only if every hop re-exports it.

    The reference fold decides which module ends up bound by ``Thing``; the
    analyser has to agree. The reverse direction matters too: a chain that did
    carry the name all the way must resolve it, or a real dependency would
    disappear from the report. The barrel's own explicit selection is asserted
    alongside, because that half of the model must not depend on the chain.
    """
    expected = _chain_supplies(links)[0]

    with _chain_index(links, is_cyclic=is_cyclic) as index:
        resolution = index.resolve("pkg.m0.Thing")
        exports = index.wildcard_exports("pkg")
        origins = index.origins_for("pkg.m0.Thing")

    assert (resolution is Resolution.RESOLVED) == expected, (
        f"chain {links!r} (cyclic={is_cyclic}) should supply Thing={expected}, "
        f"got {resolution!r} with origins {origins!r}"
    )
    assert "pkg.Thing" in exports, (
        f"the barrel's explicit selection must stay exported, got {exports!r}"
    )


@given(st.lists(_CHAIN_LINK, max_size=4))
def test_origin_chain_records_what_the_reference_fold_says_is_reachable(
    links: list[str],
) -> None:
    """A reachable re-export chain attributes the name to each module on it.

    Recording only the first or last hop would let a forbidden intermediate
    origin escape policy, because the edge would be classified as the defining
    module's group alone. The reference fold says which modules supply the
    name; the analyser must record exactly those, in chain order, and every
    entry must sit under the scanned package.
    """
    expected = _chain_origins(links)
    with _chain_index(links, is_cyclic=False) as index:
        origins = index.origins_for("pkg.m0.Thing")

    assert origins == expected, (
        f"chain {links!r} must record exactly the supplying modules: "
        f"got {origins!r}, expected {expected!r}"
    )
    assert all(origin.startswith("pkg.") for origin in origins), (
        f"every origin must sit under the scanned package, got {origins!r}"
    )
