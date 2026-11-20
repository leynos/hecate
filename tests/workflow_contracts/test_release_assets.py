"""Unit tests for :mod:`scripts.release_assets`.

The release workflow's own steps are exercised end to end in
``test_release_reconciliation.py``; these tests pin the small decisions that
run decides, so a failure names the rule rather than the whole pipeline.
"""

from __future__ import annotations

import typing as typ

import pytest

from scripts import release_assets, release_policy
from scripts.release_assets import PypiFile, State
from scripts.release_policy import Source

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


def test_the_canonical_digest_comes_from_the_source_the_plan_chose() -> None:
    """Each name reports its plan's source and that source's digest.

    The decision takes the digest listings and nothing else, so the policy is
    exercised without creating a file or a directory.
    """
    pypi = {"a.whl": "aaa"}
    github = {"b.whl": "bbb"}
    local = {"a.whl": "aaa", "b.whl": "bbb", "c.whl": "ccc"}

    assert release_policy.canonical_digest("a.whl", pypi, github, local) == (
        Source.PYPI,
        "aaa",
    ), "a name PyPI holds must report PyPI's digest"
    assert release_policy.canonical_digest("b.whl", pypi, github, local) == (
        Source.GITHUB,
        "bbb",
    ), "a name only GitHub holds must report GitHub's digest"
    assert release_policy.canonical_digest("c.whl", pypi, github, local) == (
        Source.LOCAL,
        "ccc",
    ), "a name neither destination holds must report this run's digest"


def test_the_attestation_policy_reads_only_the_digests_it_is_given() -> None:
    """A bundle is judged from the listings, with no directory to read."""
    names = ("a.whl", "b.whl")
    local = {"a.whl": "aaa", "b.whl": "bbb"}

    assert release_policy.attests_shipped_bytes(names, {}, {}, local), (
        "a first release attests the bytes it ships"
    )
    assert release_policy.attests_shipped_bytes(
        names, {"a.whl": "aaa"}, {"b.whl": "bbb"}, local
    ), "a rebuild that matches both destinations is still attested"
    assert not release_policy.attests_shipped_bytes(
        names, {"a.whl": "zzz"}, {}, local
    ), "a differing published digest must not be attested"
    assert not release_policy.attests_shipped_bytes(
        names, {}, {"b.whl": None}, local
    ), "a published digest GitHub does not report must not be attested"


def test_carryover_lists_only_names_both_sides_hold() -> None:
    """Only a name this run built *and* the release holds is carried over.

    The decision takes the two listings, so a test states them without a
    publish directory to read.
    """
    names = ("a.whl", "c.whl", "b.tar.gz")
    github = {"b.tar.gz": "bbb", "d.whl": "ddd"}

    assert release_policy.carryover(names, github) == ["b.tar.gz"], (
        "only the names both sides hold are carried over, sorted"
    )


def test_verification_names_each_disagreement_from_digests_alone() -> None:
    """The whole rule runs on plain values, with no directory to read."""
    facts = release_policy.Verification(
        names=("a.whl", "b.whl"),
        pypi_digests={"a.whl": "aaa", "b.whl": "bbb"},
        github_digests={"a.whl": "aaa", "b.whl": "ccc"},
        local_digests={"a.whl": "aaa", "b.whl": "bbb"},
        bundle_filenames=("h.sigstore.json",),
    )

    assert release_policy.verification_problems(facts) == [
        "b.whl differs: PyPI sha256 bbb, GitHub sha256 ccc",
        "h.sigstore.json is missing from the GitHub Release",
    ], "a differing name and a missing bundle are both reported"


def test_verification_does_not_demand_a_bundle_the_run_did_not_attest() -> None:
    """A run that shipped other bytes has no truthful bundle to offer."""
    facts = release_policy.Verification(
        names=("a.whl",),
        pypi_digests={"a.whl": "aaa"},
        github_digests={"a.whl": "aaa"},
        local_digests={"a.whl": "zzz"},
        bundle_filenames=("h.sigstore.json",),
    )

    assert release_policy.verification_problems(facts) == [], (
        "a bundle that would attest a different build must not be required"
    )


def test_absent_bundles_names_only_what_the_release_lacks() -> None:
    """A bundle the release already holds is not reported missing."""
    bundled = ("h-2.sigstore.json", "h-1.sigstore.json")
    github = {"h-1.sigstore.json": "bbb", "h-1.whl": None}

    assert release_policy.absent_bundles(bundled, github) == [
        "h-2.sigstore.json is missing from the GitHub Release"
    ], "only the bundle the release lacks is reported, sorted"


def test_a_published_release_cannot_accept_a_name_it_lacks() -> None:
    """Only a name the release already holds is reachable once it is published."""
    names = ("a.whl", "b.whl")

    assert release_policy.unreachable_published_uploads(names, {"a.whl": "aa"}) == (
        "b.whl",
    ), "a name a published release lacks can never be added to it"
    assert not release_policy.unreachable_published_uploads(
        names, {"a.whl": "aa", "b.whl": None}
    ), "a held name is reachable even when GitHub reports no digest"
    assert release_policy.unreachable_published_uploads(names, {}) == names, (
        "a published release holding nothing can accept nothing"
    )


def test_staging_refuses_a_published_release_before_pypi_changes(
    tmp_path: pth.Path,
) -> None:
    """PyPI must not gain bytes that a published release can never hold."""
    publish = _built(tmp_path / "publish", "a.whl", "b.whl")
    state = _state(publish, github={"a.whl": "aa"})
    before = _snapshot(publish)

    with pytest.raises(release_assets.ReleaseAssetError, match=r"cannot accept b\.whl"):
        release_assets.stage_pypi(state, tmp_path / "files", published=True)

    assert _snapshot(publish) == before, (
        "the refusal must come before any copy or removal"
    )


def test_staging_a_draft_release_keeps_the_upload_it_needs(tmp_path: pth.Path) -> None:
    """A draft can still receive the names it lacks, so staging proceeds."""
    publish = _built(tmp_path / "publish", "a.whl", "b.whl")
    state = _state(publish, pypi={"a.whl": "canonical"})

    assert release_assets.stage_pypi(state, tmp_path / "files") is True, (
        "a draft release must keep the upload it needs"
    )
    assert [path.name for path in publish.iterdir()] == ["b.whl"], (
        "the name PyPI already holds must be dropped from the upload set"
    )


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
        """Record one listing of ``directory`` and pass its names through."""
        reads.append(directory)
        return original(directory)

    monkeypatch.setattr(release_assets, "local_names", counting)

    if command == "verify":
        release_assets.verify(state, bundles)
    else:
        release_assets.stage_github(state, bundles, tmp_path / "out")

    assert reads.count(publish) == 1, (
        f"{command} must read the publish directory once, not once per decision"
    )
    assert reads.count(bundles) == 1, (
        f"{command} must read the attestation directory once, through its query"
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


def test_the_digest_query_reports_a_missing_artefact(tmp_path: pth.Path) -> None:
    """Hashing a staged name that is not there fails at the query boundary."""
    publish = _built(tmp_path / "publish", "safe.whl")

    with pytest.raises(FileNotFoundError):
        State(publish, {}, {}).local_digests(("safe.whl", "absent.whl"))


def test_the_bundle_query_reports_a_missing_directory(tmp_path: pth.Path) -> None:
    """A missing attestation directory is an error, not an empty answer."""
    with pytest.raises(FileNotFoundError):
        release_assets.bundle_names(tmp_path / "absent")


def test_verify_reports_a_missing_attestation_directory(tmp_path: pth.Path) -> None:
    """The bundle read is part of verification, and its failure surfaces."""
    publish = _built(tmp_path / "publish", "h-1.whl")

    with pytest.raises(FileNotFoundError):
        release_assets.verify(_state(publish), tmp_path / "absent")


def test_verify_refuses_an_unsafe_publish_name(tmp_path: pth.Path) -> None:
    """Verification inherits the name check the publish directory applies."""
    publish = _built(tmp_path / "publish", "safe.whl")
    (publish / "unsafe name.whl").write_bytes(b"built")
    bundles = tmp_path / "bundles"
    bundles.mkdir()

    with pytest.raises(release_assets.ReleaseAssetError, match="unsafe artefact"):
        release_assets.verify(_state(publish), bundles)


def _snapshot(*directories: pth.Path) -> dict[str, tuple[bytes, int]]:
    """Return every file's bytes and modification time, keyed by its path."""
    return {
        str(path): (path.read_bytes(), path.stat().st_mtime_ns)
        for directory in directories
        for path in sorted(directory.iterdir())
    }


def test_verify_writes_nothing_to_either_directory(tmp_path: pth.Path) -> None:
    """A check that reported a problem must still leave both sides untouched."""
    publish = _built(tmp_path / "publish", "h-1.whl")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "h-1.sigstore.json").write_bytes(b"bundle")
    before = _snapshot(publish, bundles)

    problems = release_assets.verify(_state(publish), bundles)

    assert problems, "this fixture must exercise a failing verification"
    assert _snapshot(publish, bundles) == before, (
        "verification must not add, remove, or rewrite a staged file"
    )


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
    assert release_policy.missing_from_index(expected_names, listed) == missing, (
        "the poll must list exactly the names the index still lacks"
    )
