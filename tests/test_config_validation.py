"""Tests for Hecate TOML configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from config_fixtures import assert_config_rejects as _assert_config_rejects

from hecate.config import load_config
from hecate.policy import first_matching_group


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
        "remove the unreachable prefix",
        "move it to the group that should own it",
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
        "remove the duplicate prefix 'sample.api' from later group 'composition_root'",
    )


def test_duplicate_prefix_diagnostic_covers_all_earlier_containing_prefixes(
    tmp_path: Path,
) -> None:
    """A repair must remove every earlier prefix that still shadows the later one."""
    (tmp_path / "pkg").mkdir()
    _assert_config_rejects(
        tmp_path,
        """
[tool.hecate]
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "earlier"
prefixes = ["pkg.api", "pkg"]
allowed = ["earlier", "later"]

[[tool.hecate.groups]]
name = "later"
prefixes = ["pkg.api"]
allowed = ["later", "earlier"]
""",
        "remove the duplicate prefix 'pkg.api' from later group 'later'",
        "remove every earlier prefix that contains 'pkg.api'",
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
