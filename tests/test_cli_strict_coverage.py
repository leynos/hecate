"""CLI behaviour for strict mode and coverage reporting.

Both flags change what a run reports and which exit code it returns, so they
are load-bearing for CI. These tests drive the real command rather than the
renderers, because the flag wiring between the TOML configuration, the CLI
override, and the renderer is what can silently invert.
"""

from __future__ import annotations

import json
import typing as typ
from pathlib import Path

from hecate.cli import main

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


_STRICT_CONFIG = """
[tool.hecate]
strict = true
root_packages = ["pkg"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["pkg.adapters"]
allowed = ["adapter"]
"""


def _write_package_with_unclassified_edge(root: Path) -> None:
    """Create a package whose domain imports a module no group classifies.

    The edge is internal and resolvable, so it is unclassified rather than
    unresolved: strict mode rejects it, and non-strict mode reports it as
    coverage. That asymmetry is what makes it useful for testing both flags.
    """
    package_root = root / "pkg"
    domain_root = package_root / "domain"
    domain_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (domain_root / "__init__.py").write_text("", encoding="utf-8")
    (domain_root / "model.py").write_text(
        "from ..unclassified import thing\n", encoding="utf-8"
    )
    (package_root / "unclassified.py").write_text("thing = 1\n", encoding="utf-8")


def _write_config(root: Path, *, strict: bool) -> Path:
    """Write the shared configuration with the requested strict setting."""
    config = root / "pyproject.toml"
    body = _STRICT_CONFIG if strict else _STRICT_CONFIG.replace("strict = true\n", "")
    config.write_text(body, encoding="utf-8")
    return config


def test_cli_no_strict_overrides_a_strict_config(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """``--no-strict`` cancels the configured strict mode.

    The override exists so a developer can inspect a strict project without
    editing its configuration. If it were ignored, an unclassified edge would
    still fail the check and the documented escape hatch would not exist.
    """
    _write_package_with_unclassified_edge(tmp_path)
    config = _write_config(tmp_path, strict=True)

    exit_code = main(["check", "--config", str(config), "--no-strict"])

    output = capsys.readouterr().out
    assert exit_code == 0, (
        f"--no-strict must clear the configured strict mode, got {output!r}"
    )


def test_cli_strict_config_still_fails_without_the_override(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The same fixture fails when strict mode is left in force.

    Without this control the override test would pass even if strict mode had
    stopped working, so the pair pins both directions of the flag.
    """
    _write_package_with_unclassified_edge(tmp_path)
    config = _write_config(tmp_path, strict=True)

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 1, (
        f"strict mode must reject an unclassified internal edge, got {output!r}"
    )


def test_cli_text_hides_coverage_without_the_flag(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Text output stays quiet about coverage unless asked.

    Coverage is informational in non-strict mode, so an existing consumer's
    snapshot must not change merely because coverage is now tracked.
    """
    _write_package_with_unclassified_edge(tmp_path)
    config = _write_config(tmp_path, strict=False)

    exit_code = main(["check", "--config", str(config)])

    output = capsys.readouterr().out
    assert exit_code == 0, f"a warning-only edge must not fail, got {output!r}"
    assert "unclassified" not in output, (
        f"coverage must stay hidden by default, got {output!r}"
    )


def test_cli_text_shows_coverage_with_the_flag(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """``--show-coverage`` surfaces the unclassified edge in text output."""
    _write_package_with_unclassified_edge(tmp_path)
    config = _write_config(tmp_path, strict=False)

    exit_code = main(["check", "--config", str(config), "--show-coverage"])

    output = capsys.readouterr().out
    assert exit_code == 0, f"a warning-only edge must not fail, got {output!r}"
    assert "unclassified" in output, (
        f"--show-coverage must render the unclassified edge, got {output!r}"
    )
    assert "pkg.unclassified" in output, (
        f"the unclassified target must be named, got {output!r}"
    )


def test_cli_json_reports_coverage_regardless_of_the_flag(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """JSON always carries coverage, so machine consumers need one invocation.

    The text flag deliberately does not apply to JSON: a machine consumer
    cannot see a warning it was never sent, and asking for ``--format json``
    already opts into the richer payload.
    """
    _write_package_with_unclassified_edge(tmp_path)
    config = _write_config(tmp_path, strict=False)

    exit_code = main(["check", "--config", str(config), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, f"a warning-only edge must not fail, got {payload!r}"
    assert payload["coverage"], (
        f"JSON must carry the unclassified edge without a flag, got {payload!r}"
    )
    assert payload["coverage"][0]["state"] == "unclassified", (
        f"the entry must name its state, got {payload!r}"
    )
