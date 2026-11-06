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

from scripts import release_assets
from scripts.release_assets import PypiFile, Source, State

if typ.TYPE_CHECKING:
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

    assert release_assets.attests_canonical_bytes(state) is all(
        name in matching for name in published
    ), "the bundle is truthful only when every canonical digest is this build's"
