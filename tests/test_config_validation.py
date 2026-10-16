"""Unit tests for Hecate configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from hecate.config import ConfigError, PackageRoot, load_config


def _assert_config_rejects(
    tmp_path: Path,
    toml_text: str,
    *expected_substrings: str,
) -> None:
    """Scaffold a temp config and assert ``load_config`` raises ``ConfigError``.

    The config file path and every string in *expected_substrings* must appear in
    the resulting error message.
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


def test_config_validation_rejects_unknown_allowed_group(tmp_path: Path) -> None:
    """Policy validation reports unknown group names."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["missing"]
""",
        "undeclared groups",
    )


def test_config_validation_rejects_malformed_ignore_import(
    tmp_path: Path,
) -> None:
    """Policy validation rejects malformed ignore dotted strings."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]

[[tool.hecate.ignore_imports]]
importer = "pkg..domain"
imported = "pkg.other"
reason = "Malformed entry should fail."
""",
        "ignore_imports entry",
        "pkg..domain",
    )


def test_config_validation_rejects_invalid_dotted_identifier_segment(
    tmp_path: Path,
) -> None:
    """Policy validation rejects dotted strings with invalid identifiers."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.adapters-db"]
allowed = ["domain"]
""",
        "group domain",
        "pkg.adapters-db",
    )


@pytest.mark.parametrize(
    ("toml_text", "expected"),
    [
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
package = "pkg"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "tool.hecate.package must be a list of tables",
            id="package-not-a-list",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
package = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "tool.hecate.package[0] must be a table",
            id="package-entry-not-a-table",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
package = []

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "at least one package root is required",
            id="no-package-roots",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["missing"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "package root",
            id="package-root-missing",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
groups = []

[[tool.hecate.package]]
name = "pkg"
root = "pkg"
""",
            "tool.hecate.groups must be a non-empty list of tables",
            id="groups-empty",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
groups = ["domain"]

[[tool.hecate.package]]
name = "pkg"
root = "pkg"
""",
            "tool.hecate.groups[0] must be a table",
            id="groups-entry-not-a-table",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.other"]
allowed = ["domain"]
""",
            "duplicate group names",
            id="duplicate-group-names",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
ignore_imports = "pkg.a"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "tool.hecate.ignore_imports must be a list of tables",
            id="ignores-not-a-list",
        ),
        pytest.param(
            """
[tool.hecate]
root_packages = ["pkg"]
ignore_imports = ["pkg.a"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
            "tool.hecate.ignore_imports[0] must be a table",
            id="ignore-entry-not-a-table",
        ),
    ],
)
def test_config_validation_diagnostics_are_stable(
    tmp_path: Path,
    toml_text: str,
    expected: str,
) -> None:
    """Every configuration defect keeps its documented diagnostic.

    The table-list readers share one guard, so this pins the message each
    caller must produce before that guard is extracted.
    """
    _assert_config_rejects(tmp_path, toml_text, expected)


def test_package_entry_root_resolves_relative_to_the_config(tmp_path: Path) -> None:
    """An explicit ``[[tool.hecate.package]]`` entry resolves beside the config."""
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]

[[tool.hecate.package]]
name = "pkg"
root = "pkg"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    hecate_config = load_config(config)

    assert hecate_config.packages == (
        PackageRoot(name="pkg", root=tmp_path / "pkg"),
    ), f"expected the package root beside the config, got {hecate_config.packages}"


def test_config_discovery_skips_pyproject_without_hecate_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config discovery continues past pyproject files without Hecate config."""
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    child_root = tmp_path / "child"
    child_root.mkdir()
    (child_root / "pyproject.toml").write_text(
        """
[project]
name = "not-hecate"
""",
        encoding="utf-8",
    )
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(child_root)

    hecate_config = load_config()

    assert hecate_config.source_path == config, (
        f"expected discovery to skip child pyproject, got {hecate_config.source_path}"
    )
