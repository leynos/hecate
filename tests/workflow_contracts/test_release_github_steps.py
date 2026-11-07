"""Behaviour of the release workflow's GitHub Release steps.

Each step runs its checked-in script against a ``gh`` stand-in that records
every call, so the assertions are about what the release asks GitHub to do: a
re-run reuses the tag's release instead of creating a second, a new release is
drafted and marked pre-release from the version check, the draft's existing
assets are snapshotted for the PyPI job, and the release is made visible last.
The reconciling upload and digest check are covered by
``test_release_reconciliation.py``.
"""

from __future__ import annotations

import dataclasses as dc
import json
import os
import sys
import typing as typ

import pytest

from .release_workflow import (
    fake_release,
    install_tool,
    link_scripts,
    run_bash,
    step_script,
)

if typ.TYPE_CHECKING:
    import pathlib as pth

_TAG = "v1.2.3"
_BUNDLE = f"hecate-enforce-{_TAG}.sigstore.json"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The release workflow's steps run under Bash on Linux.",
)


@dc.dataclass(frozen=True, slots=True)
class _View:
    """What the ``gh release view`` stand-in reports."""

    status: int = 0
    error: str = "release not found"


_VIEW_FOUND = _View()


def _run_with_fake_gh(
    tmp_path: pth.Path,
    script: str,
    *,
    view: _View = _VIEW_FOUND,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, list[list[str]]]:
    """Run ``script`` with a recording ``gh``; return status, stderr, and calls.

    ``gh`` writes its failure to standard error, so the stand-in does too; the
    step distinguishes "no release yet" by that message rather than by the
    exit status alone.
    """
    calls = tmp_path / "gh-calls"
    install_tool(
        tmp_path / "tools",
        "gh",
        'printf \'%s\\n\' "$*" >> "${GH_CALLS}"\n'
        'if [ "$1 $2" = "release view" ]; then\n'
        '  case "$*" in\n'
        "    *--jq*) printf '%s\\n' \"${GH_IS_DRAFT}\";;\n"
        "    *--json\\ assets*) printf '{\"assets\": []}\\n';;\n"
        "  esac\n"
        '  if [ "${GH_VIEW_STATUS}" -ne 0 ]; then\n'
        "    printf '%s\\n' \"${GH_VIEW_ERROR}\" >&2\n"
        "  fi\n"
        '  exit "${GH_VIEW_STATUS}"\n'
        "fi",
    )
    env = {
        "PATH": os.pathsep.join((str(tmp_path / "tools"), os.defpath)),
        "GH_CALLS": str(calls),
        "GH_VIEW_STATUS": str(view.status),
        "GH_VIEW_ERROR": view.error,
        "GH_IS_DRAFT": "true",
        "GITHUB_REF_NAME": _TAG,
        **(extra_env or {}),
    }
    completed = run_bash(script, tmp_path, env)
    recorded = (
        [line.split() for line in calls.read_text(encoding="utf-8").splitlines()]
        if calls.exists()
        else []
    )
    return completed.returncode, completed.stderr, recorded


def test_an_existing_release_is_reused(tmp_path: pth.Path) -> None:
    """A re-run finds the tag's release and creates nothing."""
    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("draft-release", "Create or reuse the draft release"),
        extra_env={"IS_PRERELEASE": "false"},
    )

    assert status == 0, stderr
    assert calls == [["release", "view", _TAG]], "an existing release must be reused"


@pytest.mark.parametrize(
    ("is_prerelease", "expect_prerelease_flag"),
    [("true", True), ("false", False)],
    ids=["prerelease", "final"],
)
def test_a_missing_release_is_created_as_a_draft(
    tmp_path: pth.Path, is_prerelease: str, *, expect_prerelease_flag: bool
) -> None:
    """A first run drafts the release and carries the pre-release status."""
    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("draft-release", "Create or reuse the draft release"),
        view=_View(status=1),
        extra_env={"IS_PRERELEASE": is_prerelease},
    )

    assert status == 0, stderr
    assert len(calls) == 2, f"expected a lookup then a create, got {calls}"
    create = calls[1]
    assert create[:3] == ["release", "create", _TAG], create
    assert {"--draft", "--verify-tag", "--generate-notes"} <= set(create), (
        "the release must start as a draft of the pushed tag"
    )
    assert ("--prerelease" in create) is expect_prerelease_flag, (
        "the pre-release flag must follow the version check"
    )


def test_an_unreadable_release_stops_before_creating(tmp_path: pth.Path) -> None:
    """An access or network failure is not mistaken for "no release yet"."""
    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("draft-release", "Create or reuse the draft release"),
        view=_View(status=1, error="HTTP 403: Resource not accessible by integration"),
        extra_env={"IS_PRERELEASE": "false"},
    )

    assert status != 0, "an unreadable release must fail the step"
    assert "Resource not accessible" in stderr, (
        "the failure must preserve gh's diagnostic"
    )
    assert calls == [["release", "view", _TAG]], (
        "a failed lookup must not be followed by a create"
    )


def test_the_draft_check_reports_a_draft_release(tmp_path: pth.Path) -> None:
    """The upload decision is told to proceed while the release is a draft."""
    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("publish-release", "Note whether the release is a draft"),
        extra_env={"GITHUB_OUTPUT": str(tmp_path / "output")},
    )

    assert status == 0, stderr
    assert "is-draft=true" in (tmp_path / "output").read_text(encoding="utf-8"), (
        "a draft release must be recorded as uploadable"
    )
    assert calls == [
        ["release", "view", _TAG, "--json", "isDraft", "--jq", ".isDraft"]
    ], "the step must read only the draft flag"


def test_the_draft_check_reports_a_published_release(tmp_path: pth.Path) -> None:
    """Once the release is public the check says so, and nothing is uploaded."""
    status, stderr, _ = _run_with_fake_gh(
        tmp_path,
        step_script("publish-release", "Note whether the release is a draft"),
        extra_env={
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GH_IS_DRAFT": "false",
        },
    )

    assert status == 0, stderr
    output = (tmp_path / "output").read_text(encoding="utf-8")
    assert "is-draft=false" in output, (
        "a published release must not be recorded as uploadable"
    )
    assert "nothing will be uploaded" in stderr, (
        "the step must say that a published release receives nothing"
    )


def test_the_upload_declines_a_published_release(tmp_path: pth.Path) -> None:
    """A re-run against a public release asks GitHub to change nothing."""
    staged = tmp_path / "github-upload"
    staged.mkdir()
    (staged / _BUNDLE).write_bytes(b"bundle")

    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("publish-release", "Upload the assets the release lacks"),
        extra_env={"IS_DRAFT": "false"},
    )

    assert status == 0, stderr
    assert calls == [], "a published release must not receive another asset"


def test_the_snapshot_carries_the_release_bytes_for_this_runs_names(
    tmp_path: pth.Path,
) -> None:
    """Only assets sharing a name with this run's artefacts are downloaded."""
    fake = fake_release(tmp_path)
    link_scripts(tmp_path)
    publish = tmp_path / "dist" / "publish"
    publish.mkdir(parents=True)
    for name in (
        "hecate_enforce-1.2.3-py3-none-any.whl",
        "hecate_enforce-1.2.3.tar.gz",
    ):
        (publish / name).write_bytes(b"rebuilt")
    for name in ("hecate_enforce-1.2.3.tar.gz", "hecate_enforce-1.2.2.tar.gz", _BUNDLE):
        (fake.github / name).write_bytes(b"published")

    completed = run_bash(
        step_script("draft-release", "Snapshot the release assets"),
        tmp_path,
        fake.env(GITHUB_REF_NAME=_TAG),
    )

    assert completed.returncode == 0, completed.stderr
    state = tmp_path / "github-state"
    carried = {path.name: path.read_bytes() for path in (state / "files").iterdir()}
    assert carried == {"hecate_enforce-1.2.3.tar.gz": b"published"}, (
        "the PyPI job needs GitHub's bytes for exactly the names both share"
    )
    listed = json.loads((state / "assets.json").read_text(encoding="utf-8"))
    assert len(listed["assets"]) == 3, "the snapshot must list every asset"
    assert [call[:2] for call in fake.calls("gh")] == [
        ["release", "view"],
        ["release", "download"],
    ], "the snapshot only reads the release"


@pytest.mark.parametrize("is_prerelease", ["true", "false"])
def test_the_release_is_published_with_its_prerelease_status(
    tmp_path: pth.Path, is_prerelease: str
) -> None:
    """The draft is made visible, keeping the version check's status."""
    status, stderr, calls = _run_with_fake_gh(
        tmp_path,
        step_script("publish-release", "Publish the GitHub Release"),
        extra_env={"IS_PRERELEASE": is_prerelease},
    )

    assert status == 0, stderr
    assert calls == [
        ["release", "edit", _TAG, "--draft=false", f"--prerelease={is_prerelease}"]
    ], "the run must un-draft the release with the version check's flag"
