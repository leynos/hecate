"""Unit tests for :mod:`scripts.release_index`.

The index and release readers are exercised end to end through the workflow's
steps in ``test_release_publish_steps.py``; these tests pin the release-state
read that decides whether a name can still be added to the release at all.
"""

from __future__ import annotations

import json
import typing as typ

import pytest

from scripts.release_index import release_is_published

if typ.TYPE_CHECKING:
    import pathlib as pth


def _snapshot(tmp_path: pth.Path, **fields: object) -> pth.Path:
    """Write a ``gh release view --json assets,isDraft`` response."""
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"assets": [], **fields}), encoding="utf-8")
    return path


def test_a_draft_release_is_not_published(tmp_path: pth.Path) -> None:
    """A draft can still receive the names it lacks."""
    assert release_is_published(_snapshot(tmp_path, isDraft=True)) is False, (
        "a draft must not read as published"
    )


def test_a_published_release_is_not_a_draft(tmp_path: pth.Path) -> None:
    """A published release can no longer grow."""
    assert release_is_published(_snapshot(tmp_path, isDraft=False)) is True, (
        "a published release must read as published"
    )


def test_a_snapshot_without_the_draft_flag_is_malformed(tmp_path: pth.Path) -> None:
    """The flag is required, so a snapshot that omits it cannot be mistaken."""
    with pytest.raises(KeyError):
        release_is_published(_snapshot(tmp_path))
