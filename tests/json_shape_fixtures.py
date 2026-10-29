"""Shared helpers for tests that read a decoded JSON document.

Several contract modules parse a JSON report — Makeutil's Makefile facts, a
tool's configuration — and then assert on the shape underneath a key. The
narrowing scaffolding around that assertion is the same every time and says
nothing about what any one contract is about. It lives here for the same reason
``config_fixtures.py`` does: so each test module reads as the assertion it
makes rather than as repeated casts.

Each helper names the ``subject`` it was reading in its failure message, so a
contract that gets an unexpected shape reports which part of the document was
wrong rather than failing on a bare ``isinstance`` assertion.
"""

from __future__ import annotations

import typing as typ


def mapping(value: object, *, subject: str) -> dict[str, object]:
    """Return a JSON object, identifying the unexpected `subject` on failure."""
    assert isinstance(value, dict), f"expected {subject} to be a JSON object"
    return typ.cast("dict[str, object]", value)


def objects(value: object, *, subject: str) -> list[dict[str, object]]:
    """Return a JSON object array, identifying the unexpected `subject`."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    return [mapping(item, subject=f"{subject} item") for item in value]


def text_sequence(value: object, *, subject: str) -> tuple[str, ...]:
    """Return a JSON string array, identifying the unexpected `subject`."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    assert all(isinstance(item, str) for item in value), (
        f"expected {subject} to contain only JSON strings"
    )
    return tuple(typ.cast("list[str]", value))
