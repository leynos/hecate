"""Reconcile the release artefacts so PyPI and the GitHub Release agree.

A re-pushed tag rebuilds every artefact, and rebuilt wheels are rarely
byte-identical, so each filename's canonical bytes are the ones already
published: PyPI's first, then an existing GitHub Release asset, and this run's
freshly built and attested file only when neither destination has the name.
Each destination receives only the names it lacks and nothing is overwritten.

``scripts/release_assets_cli.py`` wraps this module in the command-line
interface ``release.yml`` calls, importing it wholesale, so it inherits that
wrapper's constraint: it executes inside the job that holds the PyPI
publishing token, so it resolves no third-party code at release time, and
every network call stays in the workflow's ``curl`` and ``gh`` steps.
"""

from __future__ import annotations

import dataclasses as dc
import enum
import os
import shutil
import sys
import typing as typ
from pathlib import Path

from scripts.release_index import (
    PypiFile,
    ReleaseAssetError,
    check_digest,
    local_names,
    read_github_assets,
    read_pypi_index,
    sha256_of,
)

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


@dc.dataclass(frozen=True, slots=True)
class State:
    """The run's artefacts and what each destination already holds."""

    publish: Path
    pypi: dict[str, PypiFile]
    github: dict[str, str | None]

    @classmethod
    def load(cls, publish: Path, index: Path | None, assets: Path | None) -> State:
        """Read the staged artefacts and whichever destination listings exist.

        ``assets`` is optional because one command reads the PyPI index alone;
        a caller that needs the release's holdings passes the listing.
        """
        pypi = read_pypi_index(index) if index is not None else {}
        return cls(publish, pypi, read_github_assets(assets) if assets else {})

    def names(self) -> tuple[str, ...]:
        """Read and validate the staged artefact names.

        Reading the directory and refusing an unsafe name are both fallible, so
        this query is explicit about it: callers that plan or verify receive
        the names it returned rather than re-reading the directory themselves.

        Returns
        -------
        tuple[str, ...]
            The staged names, sorted.

        Raises
        ------
        ReleaseAssetError
            If a staged name is not a safe path component and TSV field.
        OSError
            If the publish directory cannot be read.

        """
        return tuple(local_names(self.publish))

    def plan(self, names: cabc.Iterable[str]) -> Plan:
        """Plan uploads for ``names`` against both destinations."""
        return plan(names, self.pypi, self.github)


def carryover(state: State) -> list[str]:
    """Return the names whose GitHub bytes PyPI may need.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.

    Returns
    -------
    list[str]
        The names this run built that the GitHub Release already holds,
        sorted. ``draft-release`` downloads these so ``publish-pypi`` can
        upload GitHub's canonical bytes without holding a GitHub token.

    """
    return sorted(set(state.names()) & set(state.github))


def stage_pypi(state: State, github_files: Path) -> bool:
    """Leave in ``publish`` exactly the canonical bytes PyPI lacks.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.
    github_files : Path
        The GitHub Release assets ``draft-release`` downloaded.

    Returns
    -------
    bool
        Whether any artefact remains to upload.

    """
    decided = state.plan(state.names())
    for name, source in sorted(decided.canonical.items()):
        artefact = state.publish / name
        if source is Source.PYPI:
            print(f"::notice::Skipping {name}: already on PyPI")
            artefact.unlink()
        elif source is Source.GITHUB:
            carried = github_files / name
            check_digest(carried, state.github[name])
            print(f"::notice::Uploading the GitHub Release's bytes for {name}")
            shutil.copyfile(carried, artefact)
    if not decided.pypi_uploads:
        print("Every artefact is already on PyPI; nothing to publish.")
    return bool(decided.pypi_uploads)


def _pypi_fetch_list(
    lacking: cabc.Iterable[str], pypi: cabc.Mapping[str, PypiFile]
) -> list[tuple[str, str]]:
    """Return the PyPI (name, url) pairs to fetch, insisting on HTTPS."""
    fetch = [(name, pypi[name].url) for name in lacking if name in pypi]
    if any(not url.startswith("https://") for _, url in fetch):
        msg = "every PyPI download must use HTTPS"
        raise ReleaseAssetError(msg)
    return fetch


def _copy_pypi_gap(
    lacking: cabc.Iterable[str],
    pypi: cabc.Mapping[str, PypiFile],
    publish: Path,
    output: Path,
) -> None:
    """Copy each lacking artefact that PyPI does not list into ``output``."""
    for name in lacking:
        if name not in pypi:
            shutil.copyfile(publish / name, output / name)


def canonical_digest(state: State, name: str) -> tuple[Source, str | None]:
    """Return which source's bytes are canonical for ``name``, and their digest.

    The digest is ``None`` only for a GitHub asset whose digest GitHub did not
    report; this run's own bytes are always hashable.
    """
    source = _canonical_source(name, state.pypi, state.github)
    if source is Source.PYPI:
        return source, state.pypi[name].sha256
    if source is Source.GITHUB:
        return source, state.github[name]
    return source, sha256_of(state.publish / name)


def attests_canonical_bytes(state: State) -> bool:
    """Judge whether this run's bundle describes the bytes the release ships.

    A bundle attests the artefacts one run built. Reconciliation can instead
    publish bytes an earlier run built -- PyPI's, or an existing release
    asset's -- for some or all names, because those are canonical and are never
    overwritten, while names neither destination holds keep this run's bytes.
    Attaching this run's bundle then would put a provenance claim on the release
    that part of its own assets contradict, so the bundle is withheld unless
    every name's canonical bytes are the ones this run built and attested.

    Parameters
    ----------
    state : State
        The run's artefacts and both destinations' holdings.

    Returns
    -------
    bool
        Whether every name's canonical bytes were built by this run. A name
        whose canonical source reported no digest fails the check, because the
        bundle cannot be shown to describe it.

    """
    for name in sorted(state.names()):
        source, expected = canonical_digest(state, name)
        if source is Source.LOCAL:
            continue
        if expected is None or sha256_of(state.publish / name) != expected:
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


def _copy_unattached_bundles(bundles: Path, state: State, output: Path) -> None:
    """Copy the run's bundle into ``output`` when it attests what will ship.

    Standard error is deliberate: standard output is the caller's TSV protocol.
    """
    unattached = sorted(
        bundle for bundle in bundles.iterdir() if bundle.name not in state.github
    )
    if not unattached:
        return
    if not attests_canonical_bytes(state):
        print(
            "::notice::Not attaching this run's Sigstore bundle: the release "
            "ships bytes another run built, so the bundle would attest a "
            "different build. It remains in the attestation store.",
            file=sys.stderr,
        )
        return
    for bundle in unattached:
        shutil.copyfile(bundle, output / bundle.name)


def stage_github(state: State, bundles: Path, output: Path) -> list[tuple[str, str]]:
    """Stage what the GitHub Release lacks; return the PyPI files to fetch.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.
    bundles : Path
        The Sigstore bundles this run attested.
    output : Path
        The directory to stage the release's missing assets in.

    Returns
    -------
    list[tuple[str, str]]
        ``(name, url)`` pairs for the names whose canonical bytes are PyPI's,
        which the caller downloads and then checks with :func:`check_fetched`.

    """
    lacking = sorted(state.plan(state.names()).github_uploads)
    fetch = _pypi_fetch_list(lacking, state.pypi)
    output.mkdir(parents=True, exist_ok=True)
    _copy_pypi_gap(lacking, state.pypi, state.publish, output)
    _copy_unattached_bundles(bundles, state, output)
    return fetch


def check_fetched(state: State, output: Path) -> None:
    """Raise unless every file fetched from PyPI matches PyPI's digest.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.
    output : Path
        The directory holding the files downloaded from PyPI.

    Raises
    ------
    ReleaseAssetError
        If a downloaded file's digest differs from the index's, or the index
        reports no digest for it.

    """
    for name in sorted(state.plan(state.names()).github_uploads & set(state.pypi)):
        check_digest(output / name, state.pypi[name].sha256)


def verify(state: State, bundles: Path) -> list[str]:
    """Describe every artefact or bundle the two destinations disagree on.

    A bundle is required only when it attests the bytes the release ships; see
    :func:`attests_canonical_bytes`. A run that reconciles any name onto other
    bytes cannot truthfully attach its own, and `verify` must not demand it.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.
    bundles : Path
        The Sigstore bundles this run attested.

    Returns
    -------
    list[str]
        One message per disagreement, empty when the destinations agree.

    """
    pypi = {name: file.sha256 for name, file in state.pypi.items()}
    problems = mismatches(state.names(), pypi, state.github)
    if not attests_canonical_bytes(state):
        return problems
    missing = sorted(
        bundle.name for bundle in bundles.iterdir() if bundle.name not in state.github
    )
    absent = (f"{name} is missing from the GitHub Release" for name in missing)
    return [*problems, *absent]


def write_output(name: str, *, value: bool) -> None:
    """Append one ``true``/``false`` step output for the workflow.

    Parameters
    ----------
    name : str
        The output name the workflow reads.
    value : bool
        The value, written lowercase as GitHub Actions expects.

    Raises
    ------
    KeyError
        If ``GITHUB_OUTPUT`` is unset, which means the caller is not a step.

    """
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"{name}={str(value).lower()}\n")
