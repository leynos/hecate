"""Model one release pass over generated destination holdings.

``test_release_property.py`` generates which names each destination already
holds and asks what a release pass does with them. This module is the model
those properties run: it stages a build, models the PyPI upload and the GitHub
Release upload, and records what verification made of the result. Keeping it
here leaves the property module to state the properties themselves.
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import shutil
import typing as typ

from scripts import release_assets
from scripts.release_assets import PypiFile, State

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib as pth

NAMES = ("a.whl", "b.tar.gz", "c.whl")


@dc.dataclass
class Destinations:
    """What each destination holds, as bytes, while a run is modelled."""

    pypi: dict[str, bytes]
    github: dict[str, bytes]


def copy_of(destinations: Destinations) -> Destinations:
    """Return a snapshot a later assertion can compare against."""
    return Destinations(dict(destinations.pypi), dict(destinations.github))


def state_of(publish: pth.Path, destinations: Destinations) -> State:
    """Describe ``destinations`` as the listings the release commands read.

    Parameters
    ----------
    publish : pth.Path
        The directory holding the staged build.
    destinations : Destinations
        The bytes each destination already holds.

    Returns
    -------
    State
        The staged directory with both destinations' digests.

    """
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


def write_build(root: pth.Path, build: str, names: cabc.Iterable[str]) -> pth.Path:
    """Write one run's build and return the directory holding it."""
    dist = root / "dist"
    dist.mkdir(parents=True)
    for name in names:
        (dist / name).write_bytes(f"{build} {name}".encode())
    return dist


@dc.dataclass(frozen=True, slots=True)
class Pass:
    """How one release pass is staged: its workspace, build, and names."""

    label: str
    build: str
    names: tuple[str, ...] = NAMES


@dc.dataclass(frozen=True, slots=True)
class Outcome:
    """What a modelled pass left behind, and what ``verify`` made of it.

    ``problems`` is ``None`` when the pass stopped before verification: the
    workflow runs ``publish-release`` only after a successful PyPI upload.
    ``published`` models the workflow's gate: the release becomes visible only
    when verification reports nothing.
    """

    destinations: Destinations
    problems: list[str] | None
    published: bool = False


def reported_names(problems: cabc.Iterable[str]) -> set[str]:
    """Return the name each of ``verify``'s problem messages begins with."""
    return {problem.split()[0] for problem in problems}


def write_bundles(run_root: pth.Path) -> pth.Path:
    """Write this run's bundle and return the directory holding it."""
    bundles = run_root / "bundles"
    bundles.mkdir(parents=True)
    (bundles / "run.sigstore.json").write_bytes(b"bundle")
    return bundles


def publish_pypi(
    run_root: pth.Path,
    dist: pth.Path,
    destinations: Destinations,
    upload: cabc.Collection[str] | None,
) -> tuple[Destinations, bool]:
    """Stage and model the PyPI upload; report whether it was interrupted.

    ``upload`` names the artefacts the upload step managed to send before the
    job stopped. When it is given and the step did not send everything, the
    caller must stop: ``publish-release`` never runs after a failed upload.

    Parameters
    ----------
    run_root : pth.Path
        The directory this pass owns.
    dist : pth.Path
        This run's build.
    destinations : Destinations
        The bytes each destination holds before the upload.
    upload : collections.abc.Collection[str] | None
        The names the upload managed to send, or ``None`` when the step ran
        untouched.

    Returns
    -------
    tuple[Destinations, bool]
        The destinations after the upload, and whether it was interrupted.

    """
    publish = shutil.copytree(dist, run_root / "publish-pypi")
    github_files = run_root / "github-files"
    github_files.mkdir()
    for name, data in destinations.github.items():
        (github_files / name).write_bytes(data)
    release_assets.stage_pypi(state_of(publish, destinations), github_files)

    after = copy_of(destinations)
    staged = {path.name for path in publish.iterdir()}
    for path in sorted(publish.iterdir()):
        if upload is not None and path.name not in upload:
            continue
        assert path.name not in after.pypi, (  # noqa: S101 - a test model's guard.
            "PyPI never overwrites"
        )
        after.pypi[path.name] = path.read_bytes()
    return after, upload is not None and not staged <= set(upload)


def publish_release(
    run_root: pth.Path,
    dist: pth.Path,
    bundles: pth.Path,
    destinations: Destinations,
) -> Outcome:
    """Stage, fetch, check, and model the GitHub Release upload, then verify.

    Parameters
    ----------
    run_root : pth.Path
        The directory this pass owns.
    dist : pth.Path
        This run's build.
    bundles : pth.Path
        The directory holding this run's Sigstore bundle.
    destinations : Destinations
        The bytes each destination holds before the release is updated.

    Returns
    -------
    Outcome
        The destinations after the upload and what verification made of them.

    """
    publish = shutil.copytree(dist, run_root / "publish-release")
    state = state_of(publish, destinations)
    output = run_root / "out"
    fetch = release_assets.stage_github(state, bundles, output)
    for name, url in fetch:
        assert url.startswith("https://"), (  # noqa: S101 - a test model's guard.
            "every PyPI download must use HTTPS"
        )
        (output / name).write_bytes(destinations.pypi[name])
    release_assets.check_fetched(state, output)
    for path in sorted(output.iterdir()):
        assert path.name not in destinations.github, (  # noqa: S101 - a model guard.
            "the release never overwrites"
        )
        destinations.github[path.name] = path.read_bytes()
    # Verification reads both destinations as they stand now, exactly as the
    # workflow's digest check does after it re-fetches the index and assets.
    verified = state_of(publish, destinations)
    problems = release_assets.verify(verified, bundles)
    return Outcome(destinations, problems, published=not problems)


def release_pass(
    root: pth.Path,
    options: Pass,
    destinations: Destinations,
    upload: cabc.Collection[str] | None = None,
) -> Outcome:
    """Run one release pass against ``destinations`` and return the result.

    Each job starts from a fresh copy of the build's ``dist``, as the
    ``release-dist`` artefact hands it on.

    Parameters
    ----------
    root : pth.Path
        The directory holding every pass of one property example.
    options : Pass
        The label, build, and names this pass uses.
    destinations : Destinations
        The bytes each destination holds before the pass.
    upload : collections.abc.Collection[str] | None
        The names the PyPI upload manages to send, or ``None`` when it sends
        everything.

    Returns
    -------
    Outcome
        The destinations after the pass and what verification made of them;
        ``problems`` is ``None`` when the upload was interrupted.

    """
    # Hypothesis reuses one ``tmp_path`` across examples, so each pass starts
    # from a directory of its own name that holds nothing from an earlier one.
    run_root = root / options.label
    shutil.rmtree(run_root, ignore_errors=True)
    dist = write_build(run_root / "build", options.build, options.names)
    bundles = write_bundles(run_root)

    after_pypi, interrupted = publish_pypi(run_root, dist, destinations, upload)
    if interrupted:
        return Outcome(after_pypi, None)
    return publish_release(run_root, dist, bundles, after_pypi)


def assert_preserved(before: Destinations, after: Destinations) -> None:
    """Require that no name either destination already held has changed."""
    for name, data in before.pypi.items():
        assert after.pypi[name] == data, (  # noqa: S101 - a test model's guard.
            f"PyPI's {name} must never be overwritten"
        )
    for name, data in before.github.items():
        assert after.github[name] == data, (  # noqa: S101 - a test model's guard.
            f"the release's {name} must never be overwritten"
        )
