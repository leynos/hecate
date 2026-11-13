"""Properties every reconciliation must satisfy, over generated holdings.

The example-based tests pin the cases the workflow actually meets. These
properties cover the wider space around them: any subset of names may already
be on PyPI, on the GitHub Release, or on neither, and the decisions must still
keep canonical bytes, avoid refilling a destination, and attach a bundle only
when it describes what ships.
"""

from __future__ import annotations

import typing as typ

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scripts import release_assets, release_policy
from scripts.release_assets import PypiFile, State
from scripts.release_policy import Source

from .release_pass_model import (
    NAMES,
    Destinations,
    Pass,
    assert_preserved,
    copy_of,
    release_pass,
    reported_names,
)

if typ.TYPE_CHECKING:
    import pathlib as pth

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
    decided = release_policy.plan(local, on_pypi, on_github)

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

    problems = release_policy.mismatches(local, pypi, github)

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
    first = Destinations(
        dict.fromkeys(on_pypi, b"earlier pypi"),
        dict.fromkeys(on_github, b"earlier github"),
    )
    before = copy_of(first)

    partial = release_pass(
        tmp_path, Pass("first", "first build"), first, upload=uploaded
    )
    assert_preserved(before, partial.destinations)
    assert not (partial.published and (on_pypi & on_github)), (
        "a pre-existing conflict must keep the release a draft"
    )

    final = release_pass(tmp_path, Pass("rerun", "second build"), partial.destinations)
    assert_preserved(before, final.destinations)
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
    assert reported_names(final.problems) == on_pypi & on_github, (
        "verify must report exactly the names the destinations already disagreed on"
    )
    assert final.published is not bool(on_pypi & on_github), (
        "a rerun must publish only when no pre-existing conflict remains"
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
        """Return the bytes this destination already holds for ``name``."""
        return b"other build" if name in differing else f"{build} {name}".encode()

    final = release_pass(
        tmp_path,
        Pass("run", build),
        Destinations(
            {name: held(name) for name in on_pypi},
            {name: held(name) for name in on_github},
        ),
    )

    assert final.problems == [], "agreeing destinations must not block publication"
    assert final.published is True, "a clean verification must let the release publish"
    ships_another_build = bool(differing & published)
    assert ("run.sigstore.json" in final.destinations.github) is not (
        ships_another_build
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
    initial = Destinations(
        dict.fromkeys(on_pypi, b"earlier pypi"),
        dict.fromkeys(on_github, b"earlier github"),
    )
    complete = release_pass(tmp_path, Pass("first", "first build"), initial)
    before = copy_of(complete.destinations)
    assert complete.problems is not None
    assert complete.published is not bool(on_pypi & on_github), (
        "the first pass must publish only when no conflict existed"
    )

    rerun = release_pass(tmp_path, Pass("rerun", "second build"), complete.destinations)
    assert rerun.problems is not None

    assert rerun.destinations.pypi == before.pypi, "a rerun must not upload to PyPI"
    assert rerun.destinations.github == before.github, (
        "a rerun must not upload to the release"
    )
    assert rerun.problems == complete.problems, (
        "a rerun must not change what verification reports"
    )
    assert reported_names(rerun.problems) == on_pypi & on_github, (
        "verify must report exactly the pre-existing disagreements"
    )
    assert rerun.published is not bool(on_pypi & on_github), (
        "a rerun must publish only when no pre-existing conflict remains"
    )
