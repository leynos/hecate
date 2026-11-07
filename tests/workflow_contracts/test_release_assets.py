"""Unit tests for :mod:`scripts.release_assets`.

The release workflow's own steps are exercised end to end in
``test_release_reconciliation.py``; these tests pin the small decisions that
run decides, so a failure names the rule rather than the whole pipeline.
"""

from __future__ import annotations

import typing as typ

import pytest

from scripts import release_assets
from scripts.release_assets import PypiFile, Source, State

if typ.TYPE_CHECKING:
    import pathlib as pth


def _state(
    publish: pth.Path,
    *,
    pypi: dict[str, str] | None = None,
    github: dict[str, str | None] | None = None,
) -> State:
    """Build a ``State``; a digest of ``"canonical"`` is hashed from ``publish``.

    Any other value is used verbatim, so a test can state a digest that no
    local file holds.
    """
    declared = pypi or {}
    return State(
        publish=publish,
        pypi={
            name: PypiFile(
                sha256=(
                    release_assets.sha256_of(publish / name)
                    if digest == "canonical"
                    else digest
                ),
                url=f"https://files.test/{name}",
            )
            for name, digest in declared.items()
        },
        github=github or {},
    )


def _built(publish: pth.Path, *names: str) -> pth.Path:
    """Write this run's build of each name and return the directory."""
    publish.mkdir(parents=True, exist_ok=True)
    for name in names:
        (publish / name).write_bytes(f"built {name}".encode())
    return publish


def test_a_first_release_attests_the_bytes_it_ships(tmp_path: pth.Path) -> None:
    """Nothing is published yet, so this run's bytes are canonical everywhere."""
    publish = _built(tmp_path / "publish", "h-1.whl", "h-1.tar.gz")
    state = _state(publish)

    assert release_assets.attests_canonical_bytes(state, state.names()), (
        "a first release must attest the bytes it ships"
    )


def test_a_rerun_whose_rebuild_differs_attests_nothing(tmp_path: pth.Path) -> None:
    """PyPI's immutable bytes stay canonical, so the rebuild is not the subject."""
    publish = _built(tmp_path / "publish", "h-1.whl", "h-1.tar.gz")
    state = _state(publish, pypi={"h-1.whl": "canonical"})
    (publish / "h-1.whl").write_bytes(b"rebuilt differently")

    assert not release_assets.attests_canonical_bytes(state, state.names()), (
        "a differing rebuild must not be attested"
    )


def test_a_rerun_whose_rebuild_matches_still_attests_it(tmp_path: pth.Path) -> None:
    """A byte-identical rebuild is the published artefact, whatever its source."""
    publish = _built(tmp_path / "publish", "h-1.whl")
    state = _state(publish, pypi={"h-1.whl": "canonical"})

    assert release_assets.attests_canonical_bytes(state, state.names()), (
        "a byte-identical rebuild must still be attested"
    )


def test_an_unreported_github_digest_attests_nothing(tmp_path: pth.Path) -> None:
    """An asset GitHub will not vouch for cannot be shown to match this build."""
    publish = _built(tmp_path / "publish", "h-1.whl")
    state = _state(publish, github={"h-1.whl": None})

    assert not release_assets.attests_canonical_bytes(state, state.names()), (
        "an asset without a digest must not be attested"
    )


def test_the_canonical_digest_comes_from_the_source_the_plan_chose(
    tmp_path: pth.Path,
) -> None:
    """Each name reports its plan's source and that source's digest."""
    publish = _built(tmp_path / "publish", "a.whl", "b.whl", "c.whl")
    state = _state(
        publish,
        pypi={"a.whl": "canonical"},
        github={"b.whl": release_assets.sha256_of(publish / "b.whl")},
    )

    assert release_assets.canonical_digest(state, "a.whl") == (
        Source.PYPI,
        release_assets.sha256_of(publish / "a.whl"),
    ), "a name PyPI holds must report PyPI's digest"
    assert release_assets.canonical_digest(state, "b.whl") == (
        Source.GITHUB,
        release_assets.sha256_of(publish / "b.whl"),
    ), "a name only GitHub holds must report GitHub's digest"
    assert release_assets.canonical_digest(state, "c.whl") == (
        Source.LOCAL,
        release_assets.sha256_of(publish / "c.whl"),
    ), "a name neither destination holds must report this run's digest"


@pytest.mark.parametrize("command", ["verify", "stage-github"])
def test_one_command_lists_the_publish_directory_once(
    tmp_path: pth.Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """Every decision in one command shares the names read at the boundary."""
    publish = _built(tmp_path / "publish", "h-1.whl")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "h-1.sigstore.json").write_bytes(b"bundle")
    state = _state(publish)
    reads: list[pth.Path] = []
    original = release_assets.local_names

    def counting(directory: pth.Path) -> list[str]:
        reads.append(directory)
        return original(directory)

    monkeypatch.setattr(release_assets, "local_names", counting)

    if command == "verify":
        release_assets.verify(state, bundles)
    else:
        release_assets.stage_github(state, bundles, tmp_path / "out")

    assert len(reads) == 1, (
        f"{command} must read the directory once, not once per decision"
    )


def test_the_names_query_returns_the_staged_names_sorted(tmp_path: pth.Path) -> None:
    """The fallible read is the one place the directory is listed."""
    publish = _built(tmp_path / "publish", "b.whl", "a.whl")

    assert State(publish, {}, {}).names() == ("a.whl", "b.whl"), (
        "the query must return every staged name in a stable order"
    )
    assert sorted(path.name for path in publish.iterdir()) == ["a.whl", "b.whl"], (
        "reading the names must not alter the staged artefacts"
    )


def test_the_names_query_refuses_an_unsafe_name(tmp_path: pth.Path) -> None:
    """A name that is not a safe path and TSV field fails at the boundary."""
    publish = _built(tmp_path / "publish", "safe.whl")
    (publish / "unsafe name.whl").write_bytes(b"built")

    with pytest.raises(release_assets.ReleaseAssetError, match="unsafe artefact"):
        State(publish, {}, {}).names()


def test_the_names_query_reports_a_missing_directory(tmp_path: pth.Path) -> None:
    """A publish directory that cannot be read is an error, not an empty plan."""
    with pytest.raises(FileNotFoundError):
        State(tmp_path / "absent", {}, {}).names()


@pytest.mark.parametrize(
    ("expected_names", "listed", "missing"),
    [
        ({"a.whl"}, {"a.whl"}, []),
        ({"a.whl", "b.whl"}, {"a.whl"}, ["b.whl"]),
        (set(), set(), []),
        ({"a.whl"}, set(), ["a.whl"]),
    ],
    ids=["all-present", "one-missing", "nothing-expected", "all-missing"],
)
def test_the_missing_list_names_what_the_index_does_not_yet_show(
    expected_names: set[str], listed: set[str], missing: list[str]
) -> None:
    """The poll is over exactly the names this run must see appear."""
    assert release_assets.missing_from_index(expected_names, listed) == missing, (
        "the poll must list exactly the names the index still lacks"
    )
