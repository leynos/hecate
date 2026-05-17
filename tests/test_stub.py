"""Tests for the generated package stub."""

from __future__ import annotations

import hecate


def test_hello_returns_stub_greeting() -> None:
    """The generated package exposes a working greeting."""
    assert hecate.hello() == "hello from Python"
