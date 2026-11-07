"""Properties every reconciliation must satisfy, over generated holdings.

The example-based tests pin the cases the workflow actually meets. These
properties cover the wider space around them: any subset of names may already
be on PyPI, on the GitHub Release, or on neither, and the decisions must still
keep canonical bytes, avoid refilling a destination, and attach a bundle only
when it describes what ships.
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import shutil
import typing as typ

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scripts import release_assets
from scripts.release_assets import PypiFile, Source, State

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib as pth

NAMES = ("a.whl", "b.tar.gz", "c.whl")
#: A digest no generated file holds, so a name can be made to disagree.
_UNMATCHED = "0" * 64
_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(
    local=st.sets(st.sampled_from(NAMES)),
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_plan_prefers_published_bytes_and_never_refills_a_destination(
    local: set[str], on_pypi: set[str], on_github: set[str]
) -> None:
    """PyPI outranks the release, which outranks a rebuild, for every name."""
    decided = release_assets.plan(local, on_pypi, on_github)

    assert set(decided.canonical) == local, "only this run's names are planned"
    assert decided.pypi_uploads == frozenset(local - on_pypi), (
        "PyPI receives exactly the names it lacks"
    )
    assert decided.github_uploads == frozenset(local - on_github), (
        "the release receives exactly the names it lacks"
    )
    for name in local:
        expected = (
            Source.PYPI
            if name in on_pypi
            else Source.GITHUB
            if name in on_github
            else Source.LOCAL
        )
        assert decided.canonical[name] is expected, (
            f"{name} must take its bytes from {expected}"
        )


@given(
    local=st.sets(st.sampled_from(NAMES)),
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
    differing=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_mismatches_names_exactly_the_artefacts_that_disagree(
    local: set[str], on_pypi: set[str], on_github: set[str], differing: set[str]
) -> None:
    """The digest check fails for a name missing from either side or differing."""
    pypi = dict.fromkeys(on_pypi, "same")
    github = {name: ("other" if name in differing else "same") for name in on_github}

    problems = release_assets.mismatches(local, pypi, github)

    expected = sorted(
        name
        for name in local
        if name not in on_pypi or name not in on_github or name in differing
    )
    assert [problem.split()[0] for problem in problems] == expected, (
        "the check must report each disagreeing name once and no others"
    )


@given(
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
    matching=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_the_bundle_is_attestable_exactly_when_every_canonical_byte_is_this_build(
    tmp_path: pth.Path, on_pypi: set[str], on_github: set[str], matching: set[str]
) -> None:
    """A bundle may ride along only when it describes every shipped name."""
    publish = tmp_path / "publish"
    publish.mkdir(exist_ok=True)
    for name in NAMES:
        (publish / name).write_bytes(b"this build")
    digests = {name: release_assets.sha256_of(publish / name) for name in NAMES}
    state = State(
        publish,
        {
            name: PypiFile(
                sha256=digests[name] if name in matching else _UNMATCHED,
                url=f"https://files.test/{name}",
            )
            for name in on_pypi
        },
        {name: digests[name] if name in matching else _UNMATCHED for name in on_github},
    )

    published = on_pypi | on_github

    assert release_assets.attests_canonical_bytes(state, NAMES) is all(
        name in matching for name in published
    ), "the bundle is truthful only when every canonical digest is this build's"


@dc.dataclass
class _Destinations:
    """What each destination holds, as bytes, while a run is modelled."""

    pypi: dict[str, bytes]
    github: dict[str, bytes]


def _copy(destinations: _Destinations) -> _Destinations:
    """Return a snapshot a later assertion can compare against."""
    return _Destinations(dict(destinations.pypi), dict(destinations.github))


def _state(publish: pth.Path, destinations: _Destinations) -> State:
    """Describe ``destinations`` as the listings the release commands read."""
    return State(
        publish,
        {
            name: PypiFile(
                sha256=hashlib.sha256(data).hexdigest(),
                url=f"https://files.test/{name}",
            )
            for name, data in destinations.pypi.items()
        },
        {
            name: hashlib.sha256(data).hexdigest()
            for name, data in destinations.github.items()
        },
    )


def _build(root: pth.Path, build: str, names: cabc.Iterable[str]) -> pth.Path:
    """Write one run's build and return the directory holding it."""
    dist = root / "dist"
    dist.mkdir(parents=True)
    for name in names:
        (dist / name).write_bytes(f"{build} {name}".encode())
    return dist


@dc.dataclass(frozen=True, slots=True)
class _Pass:
    """How one release pass is staged: its workspace, build, and names."""

    label: str
    build: str
    names: tuple[str, ...] = NAMES


@dc.dataclass(frozen=True, slots=True)
class _Outcome:
    """What a modelled pass left behind, and what ``verify`` made of it.

    ``problems`` is ``None`` when the pass stopped before verification: the
    workflow runs ``publish-release`` only after a successful PyPI upload.
    """

    destinations: _Destinations
    problems: list[str] | None


def _reported_names(problems: cabc.Iterable[str]) -> set[str]:
    """Return the name each of ``verify``'s problem messages begins with."""
    return {problem.split()[0] for problem in problems}


def _bundles(run_root: pth.Path) -> pth.Path:
    """Write this run's bundle and return the directory holding it."""
    bundles = run_root / "bundles"
    bundles.mkdir(parents=True)
    (bundles / "run.sigstore.json").write_bytes(b"bundle")
    return bundles


def _publish_pypi(
    run_root: pth.Path,
    dist: pth.Path,
    destinations: _Destinations,
    upload: cabc.Collection[str] | None,
) -> tuple[_Destinations, bool]:
    """Stage and model the PyPI upload; report whether it was interrupted.

    ``upload`` names the artefacts the upload step managed to send before the
    job stopped. When it is given and the step did not send everything, the
    caller must stop: ``publish-release`` never runs after a failed upload.
    """
    publish = shutil.copytree(dist, run_root / "publish-pypi")
    github_files = run_root / "github-files"
    github_files.mkdir()
    for name, data in destinations.github.items():
        (github_files / name).write_bytes(data)
    release_assets.stage_pypi(_state(publish, destinations), github_files)

    after = _copy(destinations)
    staged = {path.name for path in publish.iterdir()}
    for path in sorted(publish.iterdir()):
        if upload is not None and path.name not in upload:
            continue
        assert path.name not in after.pypi, "PyPI never overwrites"
        after.pypi[path.name] = path.read_bytes()
    return after, upload is not None and not staged <= set(upload)


def _publish_release(
    run_root: pth.Path, dist: pth.Path, bundles: pth.Path, destinations: _Destinations
) -> _Outcome:
    """Stage, fetch, check, and model the GitHub Release upload, then verify."""
    publish = shutil.copytree(dist, run_root / "publish-release")
    state = _state(publish, destinations)
    output = run_root / "out"
    fetch = release_assets.stage_github(state, bundles, output)
    for name, url in fetch:
        assert url.startswith("https://"), "every PyPI download must use HTTPS"
        (output / name).write_bytes(destinations.pypi[name])
    release_assets.check_fetched(state, output)
    for path in sorted(output.iterdir()):
        assert path.name not in destinations.github, "the release never overwrites"
        destinations.github[path.name] = path.read_bytes()
    # Verification reads both destinations as they stand now, exactly as the
    # workflow's digest check does after it re-fetches the index and assets.
    verified = _state(publish, destinations)
    return _Outcome(destinations, release_assets.verify(verified, bundles))


def _release_pass(
    root: pth.Path,
    options: _Pass,
    destinations: _Destinations,
    upload: cabc.Collection[str] | None = None,
) -> _Outcome:
    """Run one release pass against ``destinations`` and return the result.

    Each job starts from a fresh copy of the build's ``dist``, as the
    ``release-dist`` artefact hands it on.
    """
    # Hypothesis reuses one ``tmp_path`` across examples, so each pass starts
    # from a directory of its own name that holds nothing from an earlier one.
    run_root = root / options.label
    shutil.rmtree(run_root, ignore_errors=True)
    dist = _build(run_root / "build", options.build, options.names)
    bundles = _bundles(run_root)

    after_pypi, interrupted = _publish_pypi(run_root, dist, destinations, upload)
    if interrupted:
        return _Outcome(after_pypi, None)
    return _publish_release(run_root, dist, bundles, after_pypi)


def _assert_preserved(before: _Destinations, after: _Destinations) -> None:
    """Require that no name either destination already held has changed."""
    for name, data in before.pypi.items():
        assert after.pypi[name] == data, f"PyPI's {name} must never be overwritten"
    for name, data in before.github.items():
        assert after.github[name] == data, (
            f"the release's {name} must never be overwritten"
        )


@given(
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
    uploaded=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_an_interrupted_upload_is_completed_by_the_next_run(
    tmp_path: pth.Path,
    on_pypi: set[str],
    on_github: set[str],
    uploaded: set[str],
) -> None:
    """A run that stops mid-upload leaves canonical bytes; the rerun finishes."""
    first = _Destinations(
        dict.fromkeys(on_pypi, b"earlier pypi"),
        dict.fromkeys(on_github, b"earlier github"),
    )
    before = _copy(first)

    partial = _release_pass(
        tmp_path, _Pass("first", "first build"), first, upload=uploaded
    )
    _assert_preserved(before, partial.destinations)

    final = _release_pass(
        tmp_path, _Pass("rerun", "second build"), partial.destinations
    )
    _assert_preserved(before, final.destinations)
    for name in NAMES:
        assert name in final.destinations.pypi, f"{name} must reach PyPI"
        assert name in final.destinations.github, f"{name} must reach the release"
        if name in on_pypi and name in on_github:
            # Both destinations already held it; reconciliation fills gaps and
            # never rewrites a published name, so a pre-existing disagreement
            # survives for `verify` to report.
            continue
        assert final.destinations.pypi[name] == final.destinations.github[name], (
            f"{name} must hold the same bytes on both destinations"
        )
    assert final.problems is not None, "a completed pass reaches verification"
    assert _reported_names(final.problems) == on_pypi & on_github, (
        "verify must report exactly the names the destinations already disagreed on"
    )


@given(
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
    differing=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_the_bundle_reaches_the_release_only_when_it_attests_what_ships(
    tmp_path: pth.Path,
    on_pypi: set[str],
    on_github: set[str],
    differing: set[str],
) -> None:
    """A release that ships another build's bytes carries no bundle."""
    build = "this build"
    published = on_pypi | on_github

    def held(name: str) -> bytes:
        return b"other build" if name in differing else f"{build} {name}".encode()

    final = _release_pass(
        tmp_path,
        _Pass("run", build),
        _Destinations(
            {name: held(name) for name in on_pypi},
            {name: held(name) for name in on_github},
        ),
    )

    assert final.problems == [], "agreeing destinations must not block publication"
    assert ("run.sigstore.json" in final.destinations.github) is not (
        differing & published
    ), "the bundle must ride along exactly when it describes every shipped byte"


@given(
    on_pypi=st.sets(st.sampled_from(NAMES)),
    on_github=st.sets(st.sampled_from(NAMES)),
)
@_SETTINGS
def test_a_rerun_after_a_complete_release_changes_nothing(
    tmp_path: pth.Path, on_pypi: set[str], on_github: set[str]
) -> None:
    """Once every name is on both destinations, a rebuild uploads nothing."""
    initial = _Destinations(
        dict.fromkeys(on_pypi, b"earlier pypi"),
        dict.fromkeys(on_github, b"earlier github"),
    )
    complete = _release_pass(tmp_path, _Pass("first", "first build"), initial)
    before = _copy(complete.destinations)
    assert complete.problems is not None

    rerun = _release_pass(
        tmp_path, _Pass("rerun", "second build"), complete.destinations
    )
    assert rerun.problems is not None

    assert rerun.destinations.pypi == before.pypi, "a rerun must not upload to PyPI"
    assert rerun.destinations.github == before.github, (
        "a rerun must not upload to the release"
    )
    assert rerun.problems == complete.problems, (
        "a rerun must not change what verification reports"
    )
    assert _reported_names(rerun.problems) == on_pypi & on_github, (
        "verify must report exactly the pre-existing disagreements"
    )
