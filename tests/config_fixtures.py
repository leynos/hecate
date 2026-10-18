"""Shared helper for tests that assert a configuration is rejected.

Several modules pin what ``load_config`` must refuse. The scaffolding around
that assertion — write the TOML beside a package root, call the loader, check
the error names the file — is the same every time and says nothing about what
any one test is about. It lives here for the same reason
``discovery_fixtures.py`` does: so each test module reads as the assertion it
makes rather than as repeated setup.
"""

from __future__ import annotations

import typing as typ

import pytest

from hecate.config import ConfigError, load_config

if typ.TYPE_CHECKING:
    from pathlib import Path


def assert_config_rejects(
    tmp_path: Path,
    toml_text: str,
    *expected_substrings: str,
) -> None:
    """Scaffold a temp config and assert ``load_config`` raises ``ConfigError``.

    The config file path and every string in *expected_substrings* must appear
    in the resulting error message. A ``pkg`` directory is created beside the
    config so that a rejection cannot come from a missing package root.
    """
    config = tmp_path / "pyproject.toml"
    (tmp_path / "pkg").mkdir(exist_ok=True)
    config.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    error_text = str(exc_info.value)
    assert str(config) in error_text, (
        f"expected config path {config!r} in error message: {error_text}"
    )
    for expected in expected_substrings:
        assert expected in error_text, (
            f"expected {expected!r} in error message: {error_text}"
        )
