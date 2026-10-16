"""Shared helpers for TOML configuration tests."""

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
) -> str:
    """Write config TOML and return its asserted ``ConfigError`` message."""
    config = tmp_path / "pyproject.toml"
    (tmp_path / "pkg").mkdir(exist_ok=True)
    config.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    error_text = str(exc_info.value)
    if str(config) not in error_text:
        pytest.fail(f"expected config path {config!r} in error message: {error_text}")
    for expected in expected_substrings:
        if expected not in error_text:
            pytest.fail(f"expected {expected!r} in error message: {error_text}")
    return error_text
