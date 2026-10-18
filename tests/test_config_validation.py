"""Tests for Hecate TOML configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from config_fixtures import assert_config_rejects as _assert_config_rejects

from hecate.config import load_config
from hecate.policy import Severity, first_matching_group


def test_config_validation_rejects_shadowed_narrower_prefix(
    tmp_path: Path,
) -> None:
    """A later exception cannot silently lose to an earlier broad group."""
    (tmp_path / "sample").mkdir()
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "inbound_adapter"]
""",
        "inbound_adapter",
        "sample.api",
        "composition_root",
        "sample.api.runtime",
        "place group 'composition_root' before group 'inbound_adapter'",
        "narrower classification effective",
    )


def test_equal_group_prefix_diagnostic_recommends_removal(
    tmp_path: Path,
) -> None:
    """Equal prefixes need removal because ordering only swaps the winner."""
    (tmp_path / "sample").mkdir()
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api"]
allowed = ["composition_root"]
""",
        "remove the duplicate prefix from group 'composition_root'",
    )


def test_config_rejection_lists_multiple_shadows_in_configuration_order(
    tmp_path: Path,
) -> None:
    """Each later prefix gets one diagnostic in declared order."""
    (tmp_path / "sample").mkdir()
    error_text = _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime", "sample.api.handlers"]
allowed = ["composition_root", "inbound_adapter"]
""",
        "prefix 'sample.api.runtime' in group 'composition_root'",
        "prefix 'sample.api.handlers' in group 'composition_root'",
    )

    runtime_diagnostic = error_text.index(
        "prefix 'sample.api.runtime' in group 'composition_root'"
    )
    handlers_diagnostic = error_text.index(
        "prefix 'sample.api.handlers' in group 'composition_root'"
    )
    assert runtime_diagnostic < handlers_diagnostic, (
        f"expected diagnostics in prefix order, got {error_text!r}"
    )


def test_config_rejection_only_reports_shadow_within_its_package_root(
    tmp_path: Path,
) -> None:
    """Two roots stay independent when only beta has a broad-before-narrow pair."""
    for package_root in ("alpha", "beta"):
        (tmp_path / package_root).mkdir()
    error_text = _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["alpha", "beta"]

[[tool.hecate.groups]]
name = "alpha_api"
prefixes = ["alpha.api"]
allowed = ["alpha_api"]

[[tool.hecate.groups]]
name = "beta_api"
prefixes = ["beta.api"]
allowed = ["beta_api", "beta_root"]

[[tool.hecate.groups]]
name = "beta_root"
prefixes = ["beta.api.runtime"]
allowed = ["beta_root", "beta_api"]
""",
        "prefix 'beta.api.runtime' in group 'beta_root'",
        "earlier prefix 'beta.api' in group 'beta_api'",
    )

    assert "alpha.api" not in error_text, (
        f"the independent alpha root should not be reported: {error_text!r}"
    )


@pytest.mark.parametrize(
    ("roots", "toml_text", "classifications"),
    [
        (
            ("sample",),
            """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "inbound_adapter"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]
""",
            (("sample.api.runtime", "composition_root"),),
        ),
        (
            ("sample",),
            """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "api"
prefixes = ["sample.api", "sample.canonical.ingestion"]
allowed = ["api", "siblings"]

[[tool.hecate.groups]]
name = "siblings"
prefixes = ["sample.apis", "sample.api_extra", "sample.canonical.ingestion_ports"]
allowed = ["api", "siblings"]
""",
            (
                ("sample.api", "api"),
                ("sample.apis", "siblings"),
                ("sample.api_extra", "siblings"),
                ("sample.canonical.ingestion_ports", "siblings"),
            ),
        ),
        (
            ("alpha", "beta"),
            """
[tool.hecate]
root_packages = ["alpha", "beta"]

[[tool.hecate.groups]]
name = "alpha_api"
prefixes = ["alpha.api"]
allowed = ["alpha_api", "beta_api"]

[[tool.hecate.groups]]
name = "beta_api"
prefixes = ["beta.api"]
allowed = ["alpha_api", "beta_api"]
""",
            (("alpha.api.runtime", "alpha_api"), ("beta.api.runtime", "beta_api")),
        ),
        (
            ("sample",),
            """
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample", "sample.domain"]
allowed = ["domain"]
""",
            (("sample.domain.model", "domain"),),
        ),
    ],
)
def test_config_loads_reachable_ordered_group_prefixes(
    tmp_path: Path,
    roots: tuple[str, ...],
    toml_text: str,
    classifications: tuple[tuple[str, str], ...],
) -> None:
    """Reachable exceptions, dotted siblings, roots and redundancy load."""
    for package_root in roots:
        (tmp_path / package_root).mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(toml_text, encoding="utf-8")

    loaded = load_config(config)

    for module, expected_group in classifications:
        group = first_matching_group(module, loaded.policy.groups)
        assert group is not None, f"expected a group for {module!r}"
        assert group.name == expected_group, (
            f"expected {module!r} to classify as {expected_group!r}, got {group!r}"
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


def test_config_rejects_unknown_unresolved_severity(tmp_path: Path) -> None:
    """An unknown severity name is a configuration error."""
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]
unresolved_internal_severity = "loud"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        "unresolved_internal_severity",
    )


def test_config_loads_strict_and_severity_options(tmp_path: Path) -> None:
    """Strict mode and the unresolved severity are read from TOML."""
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.hecate]
root_packages = ["pkg"]
strict = true
unresolved_internal_severity = "warning"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg"]
allowed = ["domain"]
""",
        encoding="utf-8",
    )

    hecate_config = load_config(config)

    assert hecate_config.policy.strict is True, (
        f"expected strict mode from TOML, got {hecate_config.policy!r}"
    )
    assert hecate_config.policy.unresolved_internal_severity is Severity.WARNING, (
        f"expected the configured severity, got {hecate_config.policy!r}"
    )
