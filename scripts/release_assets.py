"""Reconcile the release artefacts so PyPI and the GitHub Release agree.

A re-pushed tag rebuilds every artefact, and rebuilt wheels are rarely
byte-identical, so each filename's canonical bytes are the ones already
published: PyPI's first, then an existing GitHub Release asset, and this run's
freshly built and attested file only when neither destination has the name.
Each destination receives only the names it lacks and nothing is overwritten.

Every decision here is a function of plain values -- names, digests, and
listings -- so a test exercises it without a filesystem. :class:`State` is the
adapter: it holds the publish directory and the parsed listings, and its
queries are the only reads. Each command reads once through that adapter,
passes the values it read to the decisions, and then performs the copies or
removals the plan chose.

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


def correlation() -> str:
    """Return the field that ties one log line to one release run attempt.

    GitHub Actions exports ``GITHUB_RUN_ID`` and ``GITHUB_RUN_ATTEMPT`` to
    every step, so the messages this module prints carry the same field as the
    workflow's structured records. Outside a workflow run there is nothing to
    correlate, and the field is left out rather than invented.
    """
    run = os.environ.get("GITHUB_RUN_ID")
    if not run:
        return ""
    return f" [correlation={run}/{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}]"


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
    """The adapter that names where the release's plain values come from.

    This is the only type here that holds a path or an index adapter type, so
    it is where the reads live. Every decision below takes the values it
    gathers -- names, digests, and listings -- rather than the state itself, and
    a test can therefore state any combination without a directory to read.
    """

    publish: Path
    pypi: dict[str, PypiFile]
    github: dict[str, str | None]

    @classmethod
    def load(cls, publish: Path, index: Path | None, assets: Path | None) -> State:
        """Read the staged artefacts and whichever destination listings exist.

        ``assets`` is optional because one command reads the PyPI index alone;
        a caller that needs the release's holdings passes the listing.

        Parameters
        ----------
        publish : Path
            The directory holding this run's staged artefacts.
        index : Path | None
            A saved PyPI Simple index response, or ``None`` when the command
            does not read PyPI.
        assets : Path | None
            A saved ``gh release view --json assets`` response, or ``None``
            when the command does not read the release.

        Returns
        -------
        State
            The staged directory and each destination's holdings; an absent
            listing leaves that destination empty.

        Raises
        ------
        OSError
            If a listing that was given cannot be read.
        KeyError
            If a given listing is malformed, as ``read_pypi_index`` documents.

        """
        pypi = read_pypi_index(index) if index is not None else {}
        return cls(publish, pypi, read_github_assets(assets) if assets else {})

    def names(self) -> tuple[str, ...]:
        """Read and validate the staged artefact names.

        Reading the directory and refusing an unsafe name are both fallible, so
        this query is explicit about it: callers that plan or verify receive
        the names it returned rather than re-reading the directory themselves.
        Each command reads once and passes the result to every decision it
        makes, so one operation never sees two different listings.

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
        """Plan uploads for ``names`` against both destinations.

        Parameters
        ----------
        names : collections.abc.Iterable[str]
            The staged names, as returned by :meth:`names`.

        Returns
        -------
        Plan
            Each name's canonical source and the names each destination still
            lacks.

        """
        return plan(names, self.pypi, self.github)

    def local_digests(self, names: cabc.Iterable[str]) -> dict[str, str]:
        """Hash each named staged artefact.

        Hashing reads the filesystem and is fallible, so this query is
        explicit: the attestation policy receives the digests it returns
        rather than reading files while it decides.

        Parameters
        ----------
        names : collections.abc.Iterable[str]
            The staged names, as returned by :meth:`names`.

        Returns
        -------
        dict[str, str]
            The SHA-256 hex digest of each named artefact.

        Raises
        ------
        OSError
            If an artefact cannot be read.

        """
        return {name: sha256_of(self.publish / name) for name in names}


def bundle_names(bundles: Path) -> tuple[str, ...]:
    """Read and validate the attestation directory's filenames.

    The same read boundary the publish directory has, for the other directory a
    command inspects: callers receive the names and never list the directory
    themselves.

    Parameters
    ----------
    bundles : Path
        The directory holding this run's Sigstore bundles.

    Returns
    -------
    tuple[str, ...]
        The bundle filenames, sorted.

    Raises
    ------
    ReleaseAssetError
        If a bundle's name is not a safe path component and TSV field.
    OSError
        If the attestation directory cannot be read.

    """
    return tuple(local_names(bundles))


def carryover(
    names: cabc.Iterable[str], github_digests: cabc.Mapping[str, str | None]
) -> list[str]:
    """Return the names whose GitHub bytes PyPI may need.

    The decision is a function of the staged names and the release's holdings
    alone; reading the publish directory stays at the caller's boundary.

    Parameters
    ----------
    names : collections.abc.Iterable[str]
        The staged names, as returned by :meth:`State.names`.
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
        The staged names, as returned by :meth:`State.names`.
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


def stage_pypi(state: State, github_files: Path, *, published: bool = False) -> bool:
    """Leave in ``publish`` exactly the canonical bytes PyPI lacks.

    Parameters
    ----------
    state : State
        The staged artefacts and both destinations' holdings.
    github_files : Path
        The GitHub Release assets ``draft-release`` downloaded.
    published : bool
        Whether the tag's release is already published. Such a release cannot
        accept a name it lacks, so staging stops before PyPI changes.

    Returns
    -------
    bool
        Whether any artefact remains to upload.

    Raises
    ------
    ReleaseAssetError
        If the release is published and lacks a staged name.

    """
    names = state.names()
    unreachable = unreachable_published_uploads(names, state.github)
    if published and unreachable:
        msg = (
            "the tag's GitHub Release is already published, so it cannot accept "
            f"{', '.join(unreachable)}; PyPI was not changed. Delete that "
            "release and re-run the tag's workflow, or upload those files by "
            "hand"
        )
        raise ReleaseAssetError(msg)
    decided = state.plan(names)
    for name, source in sorted(decided.canonical.items()):
        artefact = state.publish / name
        if source is Source.PYPI:
            print(f"::notice::Skipping {name}: already on PyPI{correlation()}")
            artefact.unlink()
        elif source is Source.GITHUB:
            carried = github_files / name
            check_digest(carried, state.github[name])
            print(
                f"::notice::Uploading the GitHub Release's bytes for {name}"
                f"{correlation()}"
            )
            shutil.copyfile(carried, artefact)
    if not decided.pypi_uploads:
        print(f"Every artefact is already on PyPI; nothing to publish.{correlation()}")
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


def canonical_digest(
    name: str,
    pypi_digests: cabc.Mapping[str, str],
    github_digests: cabc.Mapping[str, str | None],
    local_digests: cabc.Mapping[str, str],
) -> tuple[Source, str | None]:
    """Return which source's bytes are canonical for ``name``, and their digest.

    The decision is a function of the three digest listings alone; reading the
    staged files, and the :class:`State` that holds them, stays at the caller's
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
        The staged names, as returned by :meth:`State.names`.
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


def attests_canonical_bytes(state: State, names: cabc.Iterable[str]) -> bool:
    """Judge whether this run's bundle describes the bytes the release ships.

    The filesystem read stays explicit: every staged name is hashed through
    :meth:`State.local_digests`, and the decision itself is the pure
    :func:`attests_shipped_bytes`. See that function for the rule.

    Parameters
    ----------
    state : State
        The run's artefacts and both destinations' holdings.
    names : collections.abc.Iterable[str]
        The staged names, as returned by :meth:`State.names`. Taking them as
        input keeps one command to one directory read.

    Returns
    -------
    bool
        Whether every name's canonical bytes were built by this run.

    Raises
    ------
    OSError
        If a staged artefact cannot be read while its digest is taken.

    """
    staged = tuple(names)
    return attests_shipped_bytes(
        staged,
        {name: file.sha256 for name, file in state.pypi.items()},
        state.github,
        state.local_digests(staged),
    )


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


def _copy_unattached_bundles(
    bundles: Path, state: State, output: Path, names: cabc.Iterable[str]
) -> None:
    """Copy the run's bundle into ``output`` when it attests what will ship.

    The bundle directory is read once, here, through :func:`bundle_names`; the
    copy decision itself is the pure :func:`unattached_bundles`.

    Standard error is deliberate: standard output is the caller's TSV protocol.
    """
    missing = unattached_bundles(bundle_names(bundles), state.github)
    if not missing:
        return
    if not attests_canonical_bytes(state, names):
        print(
            "::notice::Not attaching this run's Sigstore bundle: the release "
            "ships bytes another run built, so the bundle would attest a "
            f"different build. It remains in the attestation store.{correlation()}",
            file=sys.stderr,
        )
        return
    for name in missing:
        shutil.copyfile(bundles / name, output / name)


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
    names = state.names()
    lacking = sorted(state.plan(names).github_uploads)
    fetch = _pypi_fetch_list(lacking, state.pypi)
    output.mkdir(parents=True, exist_ok=True)
    _copy_pypi_gap(lacking, state.pypi, state.publish, output)
    _copy_unattached_bundles(bundles, state, output, names)
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
    names = state.names()
    for name in sorted(state.plan(names).github_uploads & set(state.pypi)):
        check_digest(output / name, state.pypi[name].sha256)


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


def verify(state: State, bundles: Path) -> list[str]:
    """Describe every artefact or bundle the two destinations disagree on.

    This is the boundary: the staged names, their digests and the bundle
    filenames are read here, once each, and handed to the pure decision
    (:func:`verification_problems`). It writes nothing, so a failed check
    leaves both directories exactly as it found them.

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

    Raises
    ------
    ReleaseAssetError
        If a staged artefact or bundle name is not a safe path component and
        TSV field.
    OSError
        If the publish or attestation directory cannot be read, or a staged
        artefact cannot be hashed.

    """
    names = state.names()
    return verification_problems(
        Verification(
            names=names,
            pypi_digests={name: file.sha256 for name, file in state.pypi.items()},
            github_digests=state.github,
            local_digests=state.local_digests(names),
            bundle_filenames=bundle_names(bundles),
        )
    )


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
