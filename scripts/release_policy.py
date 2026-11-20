"""Decide what a release ships, from plain values alone.

Reconciliation compares three listings -- the names this run staged, PyPI's
holdings, and the GitHub Release's holdings -- and the rules are functions of
those values: names, digests, and draft or published state. Nothing here opens
a file, reads the environment, or holds a :class:`pathlib.Path`, so a test
states any combination of facts without a directory to create.

The adapter that gathers those facts lives in ``scripts/release_assets.py``: it
reads the staged directory and both listings, passes the values to the rules
here, and performs the copies and removals the rules chose. A rule that needs
bytes hashes them only through the digests its caller supplies.
"""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class Source(enum.StrEnum):
    """Where one artefact name's canonical bytes come from."""

    PYPI = "pypi"
    GITHUB = "github"
    LOCAL = "local"


@dc.dataclass(frozen=True, slots=True)
class Plan:
    """The canonical source of each name and what each destination lacks."""

    canonical: cabc.Mapping[str, Source]
    pypi_uploads: frozenset[str]
    github_uploads: frozenset[str]


def _canonical_source(
    name: str, on_pypi: cabc.Collection[str], on_github: cabc.Collection[str]
) -> Source:
    """Return the destination whose bytes win for ``name``.

    PyPI is immutable once a file is published, so it outranks the GitHub
    Release; the release outranks this run's rebuild, which may differ from
    the bytes a consumer already fetched.
    """
    if name in on_pypi:
        return Source.PYPI
    if name in on_github:
        return Source.GITHUB
    return Source.LOCAL


def plan(
    local: cabc.Iterable[str],
    on_pypi: cabc.Collection[str],
    on_github: cabc.Collection[str],
) -> Plan:
    """Choose each name's canonical bytes and the uploads each side needs.

    Parameters
    ----------
    local : collections.abc.Iterable[str]
        The artefact names this run built and attested.
    on_pypi : collections.abc.Collection[str]
        Names PyPI already holds.
    on_github : collections.abc.Collection[str]
        Names the tag's GitHub Release already holds, draft or published.

    Returns
    -------
    Plan
        PyPI takes precedence over GitHub, and GitHub over this run's bytes;
        each destination is sent exactly the names it lacks.

    Examples
    --------
    >>> plan(["p.whl"], set(), {"p.whl"}).canonical["p.whl"]
    <Source.GITHUB: 'github'>

    """
    names = frozenset(local)
    canonical = {name: _canonical_source(name, on_pypi, on_github) for name in names}
    return Plan(
        canonical=canonical,
        pypi_uploads=frozenset(name for name in names if name not in on_pypi),
        github_uploads=frozenset(name for name in names if name not in on_github),
    )


def mismatches(
    local: cabc.Iterable[str],
    pypi_digests: cabc.Mapping[str, str],
    github_digests: cabc.Mapping[str, str | None],
) -> list[str]:
    """Describe every name the two destinations do not hold identically.

    Parameters
    ----------
    local : collections.abc.Iterable[str]
        The artefact names the release must carry.
    pypi_digests : collections.abc.Mapping[str, str]
        PyPI's SHA-256 hex digest for each name it holds.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's SHA-256 hex digest per asset, ``None`` when
        GitHub reports none.

    Returns
    -------
    list[str]
        One message per missing or differing name; empty when they agree.

    Examples
    --------
    >>> mismatches(["p.whl"], {"p.whl": "ab"}, {"p.whl": "ab"})
    []

    """
    return [
        problem
        for name in sorted(set(local))
        if (problem := _mismatch(name, pypi_digests, github_digests))
    ]


def _mismatch(
    name: str,
    pypi_digests: cabc.Mapping[str, str],
    github_digests: cabc.Mapping[str, str | None],
) -> str | None:
    """Describe how one name differs between the destinations, if it does."""
    pypi, github = pypi_digests.get(name), github_digests.get(name)
    if pypi is None:
        return f"{name} is missing from PyPI"
    if github is None:
        return f"{name} is missing from the GitHub Release or has no digest"
    if pypi != github:
        return f"{name} differs: PyPI sha256 {pypi}, GitHub sha256 {github}"
    return None


def carryover(
    names: cabc.Iterable[str], github_digests: cabc.Mapping[str, str | None]
) -> list[str]:
    """Return the names whose GitHub bytes PyPI may need.

    The decision is a function of the staged names and the release's holdings
    alone; reading the publish directory stays at the caller's boundary.

    Parameters
    ----------
    names : collections.abc.Iterable[str]
        The staged names, as returned by ``State.names``.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports
        none. Only the names matter here.

    Returns
    -------
    list[str]
        The names this run built that the GitHub Release already holds,
        sorted. ``draft-release`` downloads these so ``publish-pypi`` can
        upload GitHub's canonical bytes without holding a GitHub token.

    """
    return sorted(set(names) & set(github_digests))


def unreachable_published_uploads(
    names: cabc.Iterable[str], github_digests: cabc.Mapping[str, str | None]
) -> tuple[str, ...]:
    """Return the staged names a published GitHub Release can never accept.

    A published release is immutable, so a name it lacks cannot be attached to
    it later. Uploading that name to PyPI would publish bytes that no release
    for this tag can ever match, and PyPI cannot take them back. The caller
    checks this before the upload, while both destinations are still unchanged.

    Parameters
    ----------
    names : collections.abc.Iterable[str]
        The staged names, as returned by ``State.names``.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports
        none. Only the names matter here.

    Returns
    -------
    tuple[str, ...]
        The staged names the release lacks, sorted.

    Examples
    --------
    >>> unreachable_published_uploads(("a.whl", "b.whl"), {"a.whl": None})
    ('b.whl',)

    """
    return tuple(sorted(set(names) - set(github_digests)))


def canonical_digest(
    name: str,
    pypi_digests: cabc.Mapping[str, str],
    github_digests: cabc.Mapping[str, str | None],
    local_digests: cabc.Mapping[str, str],
) -> tuple[Source, str | None]:
    """Return which source's bytes are canonical for ``name``, and their digest.

    The decision is a function of the three digest listings alone; reading the
    staged files, and the adapter that holds them, stays at the caller's
    boundary. ``local_digests`` need only hold the names this run staged.

    Parameters
    ----------
    name : str
        The artefact name to resolve.
    pypi_digests : collections.abc.Mapping[str, str]
        PyPI's SHA-256 hex digest for each name it holds.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports none.
    local_digests : collections.abc.Mapping[str, str]
        This run's SHA-256 hex digest for each staged name it hashed.

    Returns
    -------
    tuple[Source, str | None]
        The canonical source and its digest. The digest is ``None`` for a
        GitHub asset whose digest GitHub did not report, and for a name the
        chosen listing does not hold.
    """
    source = _canonical_source(name, pypi_digests, github_digests)
    if source is Source.PYPI:
        return source, pypi_digests[name]
    if source is Source.GITHUB:
        return source, github_digests[name]
    return source, local_digests.get(name)


def attests_shipped_bytes(
    names: cabc.Iterable[str],
    pypi_digests: cabc.Mapping[str, str],
    github_digests: cabc.Mapping[str, str | None],
    local_digests: cabc.Mapping[str, str],
) -> bool:
    """Judge, from digests alone, whether this run's bundle describes the release.

    A bundle attests the artefacts one run built. Reconciliation can instead
    publish bytes an earlier run built -- PyPI's, or an existing release
    asset's -- for some or all names, because those are canonical and are never
    overwritten, while names neither destination holds keep this run's bytes.
    Attaching this run's bundle then would put a provenance claim on the release
    that part of its own assets contradict, so the bundle is withheld unless
    every name's canonical bytes are the ones this run built and attested.

    Parameters
    ----------
    names : collections.abc.Iterable[str]
        The staged names, as returned by ``State.names``.
    pypi_digests : collections.abc.Mapping[str, str]
        PyPI's SHA-256 hex digest for each name it holds.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports none.
    local_digests : collections.abc.Mapping[str, str]
        This run's SHA-256 hex digest for each staged name it hashed.

    Returns
    -------
    bool
        Whether every name's canonical bytes were built by this run. A name
        whose canonical source reported no digest fails the check, because the
        bundle cannot be shown to describe it.

    """
    for name in sorted(names):
        source, expected = canonical_digest(
            name, pypi_digests, github_digests, local_digests
        )
        if source is Source.LOCAL:
            continue
        if expected is None or local_digests.get(name) != expected:
            return False
    return True


def missing_from_index(
    expected: cabc.Iterable[str], listed: cabc.Collection[str]
) -> list[str]:
    """Return the names ``expected`` that one index response does not list.

    Parameters
    ----------
    expected : collections.abc.Iterable[str]
        The names the caller needs to see in the index.
    listed : collections.abc.Collection[str]
        The filenames the index response carries.

    Returns
    -------
    list[str]
        The expected names still absent, sorted; empty once the index agrees.

    Examples
    --------
    >>> missing_from_index(["a.whl", "b.whl"], {"a.whl"})
    ['b.whl']

    """
    return sorted(set(expected) - set(listed))


def unattached_bundles(
    bundle_filenames: cabc.Iterable[str],
    github_digests: cabc.Mapping[str, str | None],
) -> tuple[str, ...]:
    """Return the bundles this run staged that the release does not hold.

    Parameters
    ----------
    bundle_filenames : collections.abc.Iterable[str]
        The bundle filenames found in the attestation directory.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports
        none. Only the names matter here.

    Returns
    -------
    tuple[str, ...]
        The names the release lacks, sorted.

    """
    return tuple(sorted(set(bundle_filenames) - set(github_digests)))


def absent_bundles(
    bundle_filenames: cabc.Iterable[str],
    github_digests: cabc.Mapping[str, str | None],
) -> list[str]:
    """Describe each bundle this run attested that the release does not hold.

    Parameters
    ----------
    bundle_filenames : collections.abc.Iterable[str]
        The bundle filenames found in the attestation directory.
    github_digests : collections.abc.Mapping[str, str | None]
        The GitHub Release's digest per asset, ``None`` when GitHub reports
        none. Only the names matter here.

    Returns
    -------
    list[str]
        One message per missing bundle, sorted; empty when the release holds
        every bundle this run staged.

    """
    return [
        f"{name} is missing from the GitHub Release"
        for name in unattached_bundles(bundle_filenames, github_digests)
    ]


@dc.dataclass(frozen=True, slots=True)
class Verification:
    """The plain values one verification decision is made from.

    No path, and no index or release adapter type, appears here. A caller that
    holds the digests and the bundle filenames can therefore exercise the whole
    rule -- including which bundles are required -- without a filesystem.
    """

    names: tuple[str, ...]
    pypi_digests: cabc.Mapping[str, str]
    github_digests: cabc.Mapping[str, str | None]
    local_digests: cabc.Mapping[str, str]
    bundle_filenames: tuple[str, ...]


def verification_problems(facts: Verification) -> list[str]:
    """Describe every artefact or bundle the two destinations disagree on.

    A bundle is required only when it attests the bytes the release ships; see
    :func:`attests_shipped_bytes`. A run that reconciles any name onto other
    bytes cannot truthfully attach its own, and this decision must not demand
    it. The rule is a function of ``facts`` alone.

    Parameters
    ----------
    facts : Verification
        The staged names, the three digest listings, and the bundle filenames.

    Returns
    -------
    list[str]
        One message per disagreement, empty when the destinations agree.

    Examples
    --------
    >>> facts = Verification(("p.whl",), {"p.whl": "ab"}, {"p.whl": "ab"},
    ...                      {"p.whl": "ab"}, ("b.sigstore.json",))
    >>> verification_problems(facts)
    ['b.sigstore.json is missing from the GitHub Release']

    """
    problems = mismatches(facts.names, facts.pypi_digests, facts.github_digests)
    if not attests_shipped_bytes(
        facts.names, facts.pypi_digests, facts.github_digests, facts.local_digests
    ):
        return problems
    return [*problems, *absent_bundles(facts.bundle_filenames, facts.github_digests)]
