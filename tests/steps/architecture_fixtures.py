"""Fixture packages and policies for the architecture-check scenarios.

The scenario steps drive the CLI; everything a scenario *is* -- the package
tree, the import under test, and the TOML policy that judges it -- lives here
as data. Keeping it separate lets a new scenario declare a fixture by adding
one entry rather than by adding branching setup code.
"""

from __future__ import annotations

import dataclasses as dc
from pathlib import Path


def _write_base_package(package_root: Path) -> None:
    """Write the shared sample package skeleton beneath ``package_root``."""
    for directory in (
        package_root,
        package_root / "domain",
        package_root / "application",
        package_root / "adapters",
        package_root / "adapters" / "outbound",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "config.py").write_text("", encoding="utf-8")
    (package_root / "cli.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "model.py").write_text("", encoding="utf-8")
    (package_root / "domain" / "port.py").write_text("", encoding="utf-8")
    (package_root / "application" / "service.py").write_text("", encoding="utf-8")
    (package_root / "adapters" / "outbound" / "db.py").write_text("", encoding="utf-8")


@dc.dataclass(frozen=True, slots=True)
class FixtureVariant:
    """One named fixture: the edge to check plus any barrel files it needs.

    ``extra`` holds package-barrel sources written before the import site, so
    variants that exercise re-export semantics declare their barrels as data
    rather than as branching setup code.
    """

    target: str
    contents: str
    extra: tuple[tuple[str, str], ...] = ()


_EXPOSED_BARREL = (
    "adapters/__init__.py",
    "from .outbound import db\n__all__ = ['db']\n",
)

_HIDDEN_BARREL = (
    "adapters/__init__.py",
    "from .outbound import db\n__all__ = []\n",
)

_FIXTURE_VARIANTS: dict[str, FixtureVariant] = {
    "clean_package": FixtureVariant(
        "application/service.py", "from sample.domain import model\n"
    ),
    "domain_imports_adapter": FixtureVariant(
        "domain/model.py", "from sample.adapters.outbound import db\n"
    ),
    "application_imports_adapter": FixtureVariant(
        "application/service.py", "from sample.adapters.outbound import db\n"
    ),
    "application_imports_domain_port": FixtureVariant(
        "application/service.py", "from sample.domain import port\n"
    ),
    "composition_root_wires_adapters": FixtureVariant(
        "config.py", "from sample.adapters.outbound import db\n"
    ),
    "inbound_cli_imports_config": FixtureVariant(
        "cli.py", "from sample import config\n"
    ),
    "inbound_cli_imports_outbound_adapter": FixtureVariant(
        "cli.py", "from sample.adapters.outbound import db\n"
    ),
    "domain_imports_external_infrastructure": FixtureVariant(
        "domain/model.py", "import sqlalchemy\n"
    ),
    # A barrel advertising a re-export to wildcards and to explicit imports.
    "application_imports_reexported_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(_EXPOSED_BARREL,),
    ),
    # A barrel that reaches its re-export through a star import.
    "application_imports_star_reexported_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(
            ("adapters/__init__.py", "from .outbound import *\n"),
            ("adapters/outbound/__init__.py", "from . import db\n__all__ = ['db']\n"),
        ),
    ),
    # __all__ hides db from wildcards but cannot unbind it, so this explicit
    # re-export must still resolve to the outbound adapter.
    "application_imports_all_hidden_adapter": FixtureVariant(
        "application/service.py",
        "from sample.adapters import db\n",
        extra=(_HIDDEN_BARREL,),
    ),
    # A wildcard consumer, which must expand to the origin of db.
    "application_imports_wildcard_consumer": FixtureVariant(
        "application/service.py",
        "from sample.adapters import *\n",
        extra=(_EXPOSED_BARREL,),
    ),
    # A wildcard over __all__ = [] binds nothing beyond the module edge.
    "application_imports_empty_all_wildcard": FixtureVariant(
        "application/service.py",
        "from sample.adapters import *\n",
        extra=(_HIDDEN_BARREL,),
    ),
    # A relative import through a package barrel must resolve like the absolute
    # form; both spell the same edge.
    "application_imports_relative_barrel_adapter": FixtureVariant(
        "application/service.py",
        "from sample.application import db\n",
        extra=(
            ("application/__init__.py", "from ..adapters import db\n"),
            _EXPOSED_BARREL,
        ),
    ),
    # The new subtree matches no configured group, so a non-strict run passes
    # while still reporting the edge as unclassified.
    "application_imports_unclassified_subtree": FixtureVariant(
        "application/service.py",
        "from sample.newthing import helper\n",
        extra=(
            ("newthing/__init__.py", ""),
            ("newthing/helper.py", ""),
        ),
    ),
    # The symbol does not exist, so the internal edge is unresolved.
    "application_imports_unresolved_symbol": FixtureVariant(
        "application/service.py", "from sample.domain import missing_symbol\n"
    ),
}


def _write_fixture(package_root: Path, fixture: str) -> None:
    """Write one predefined fixture variant into the sample package root."""
    assert fixture in _FIXTURE_VARIANTS, (
        f"Unknown fixture {fixture!r}, valid fixtures: {sorted(_FIXTURE_VARIANTS)}"
    )
    variant = _FIXTURE_VARIANTS[fixture]
    for relative_path, contents in variant.extra:
        path = package_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    (package_root / variant.target).write_text(variant.contents, encoding="utf-8")


def _policy_toml(*, allow_everything: bool = False, warn: str = "") -> str:
    """Return the sample policy TOML, optionally allowing every group edge.

    ``warn`` adds warning targets to the application group, which is how the
    migration scenarios downgrade one real edge without changing anything else
    about the policy.
    """
    allowed = (
        '["composition_root", "domain", "application", "inbound_adapter", '
        '"outbound_adapter", "adapter", "infrastructure"]'
    )
    application_allowed = allowed if allow_everything else '["application", "domain"]'
    domain_allowed = allowed if allow_everything else '["domain"]'
    inbound_allowed = (
        allowed
        if allow_everything
        else '["inbound_adapter", "composition_root", "application", "domain"]'
    )
    application_warn = f"warn = {warn}" if warn else ""
    return f"""
[tool.hecate]
root_packages = ["sample"]
include_external_packages = true
default_rule_id = "HEC001"

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.config"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = {domain_allowed}

[[tool.hecate.groups]]
name = "application"
prefixes = ["sample.application"]
allowed = {application_allowed}
{application_warn}

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.cli", "sample.adapters.inbound"]
allowed = {inbound_allowed}

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = ["sample.adapters.outbound"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["sample.adapters"]
allowed = {allowed}

[[tool.hecate.groups]]
name = "infrastructure"
prefixes = ["sqlalchemy"]
allowed = ["infrastructure"]
"""
