"""Whole-payload snapshots for the text and JSON renderers.

The per-diagnostic tests assert the fields they care about, which leaves the
payload's overall shape unpinned: a reordering, a lost section, or a status
that disagrees with the exit code would slip past every substring assertion.
These snapshots compare the whole rendered document, so any change to it has
to be intended and reviewed.

Temporary paths are normalized to ``<tmp>`` before comparison. They are the
only variable part of the output: every other field is derived from the
fixture, which is why the expected documents can be written inline.
"""

from __future__ import annotations

import json
from pathlib import Path

from hecate.checker import ArchitectureCheckResult, check_architecture
from hecate.config import load_config
from hecate.output import render_json, render_text

#: The scanned package the snapshots share: ``application`` imports the
#: adapter at warning level, and ``domain`` imports it forbidden.
_PACKAGE_FILES = {
    "__init__.py": "",
    "application/__init__.py": "",
    "application/service.py": "from pkg.adapters import database\n",
    "adapters/__init__.py": "",
    "adapters/database.py": "",
}

#: ``application`` warns the adapter group while ``domain`` forbids it, so one
#: policy produces both diagnostic kinds.
_GROUPS = """
[[tool.hecate.groups]]
name = "application"
prefixes = ["pkg.application"]
allowed = ["application"]
warn = ["adapter"]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["pkg.adapters"]
allowed = ["adapter"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["pkg.domain"]
allowed = ["domain"]
"""


def _check(root: Path, *, with_violation: bool) -> ArchitectureCheckResult:
    """Build the shared package, check it, and return the result."""
    files = dict(_PACKAGE_FILES)
    if with_violation:
        files["domain/__init__.py"] = ""
        files["domain/model.py"] = "from pkg.adapters import database\n"
    for relative_path, contents in files.items():
        target = root / "pkg" / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    config = root / "pyproject.toml"
    config.write_text(
        '[tool.hecate]\nroot_packages = ["pkg"]\n' + _GROUPS,
        encoding="utf-8",
    )
    return check_architecture(load_config(config))


def _normalize(output: str, root: Path) -> str:
    """Replace the scratch root so a snapshot is host-independent."""
    return output.replace(str(root), "<tmp>")


def test_text_snapshot_of_a_warning_only_pass(tmp_path: Path) -> None:
    """A warning-only run passes and still names every warned edge."""
    result = _check(tmp_path, with_violation=False)

    text = _normalize(render_text(result, passed=True), tmp_path)

    assert text == (
        "hecate: architecture check passed\n"
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters (application -> adapter)\n"
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters.database (application -> adapter)\n"
    ), f"the warning-only text payload changed: {text!r}"


def test_text_snapshot_of_an_enforced_warning_run(tmp_path: Path) -> None:
    """``--fail-on-warnings`` drops the pass notice but keeps the warnings."""
    result = _check(tmp_path, with_violation=False)

    text = _normalize(render_text(result, passed=False), tmp_path)

    assert text == (
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters (application -> adapter)\n"
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters.database (application -> adapter)\n"
    ), f"the enforced-warning text payload changed: {text!r}"


def test_text_snapshot_of_a_mixed_warning_and_violation_run(
    tmp_path: Path,
) -> None:
    """Violations lead, warnings follow, and no pass notice is printed."""
    result = _check(tmp_path, with_violation=True)

    text = _normalize(render_text(result, passed=False), tmp_path)

    assert text == (
        "HEC001: pkg.domain.model:1 imports forbidden module pkg.adapters "
        "(domain -> adapter)\n"
        "HEC001: pkg.domain.model:1 imports forbidden module "
        "pkg.adapters.database (domain -> adapter)\n"
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters (application -> adapter)\n"
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        "module pkg.adapters.database (application -> adapter)\n"
    ), f"the mixed text payload changed: {text!r}"


def test_json_snapshot_of_a_warning_only_pass(tmp_path: Path) -> None:
    """JSON reports ``ok`` and ``status`` separately for a warning-only run."""
    result = _check(tmp_path, with_violation=False)

    payload = json.loads(_normalize(render_json(result, passed=True), tmp_path))

    assert payload == {
        "coverage": [],
        "ok": True,
        "status": "passed",
        "violations": [],
        "warnings": [
            _warning_entry("pkg.adapters"),
            _warning_entry("pkg.adapters.database"),
        ],
    }, f"the warning-only JSON payload changed: {payload!r}"


def test_json_snapshot_of_an_enforced_warning_run(tmp_path: Path) -> None:
    """``ok`` keeps describing the architecture while ``status`` fails."""
    result = _check(tmp_path, with_violation=False)

    payload = json.loads(_normalize(render_json(result, passed=False), tmp_path))

    assert payload == {
        "coverage": [],
        "ok": True,
        "status": "failed",
        "violations": [],
        "warnings": [
            _warning_entry("pkg.adapters"),
            _warning_entry("pkg.adapters.database"),
        ],
    }, f"the enforced-warning JSON payload changed: {payload!r}"


def test_json_snapshot_of_a_mixed_warning_and_violation_run(
    tmp_path: Path,
) -> None:
    """Both diagnostic kinds keep their own section and state."""
    result = _check(tmp_path, with_violation=True)

    payload = json.loads(_normalize(render_json(result, passed=False), tmp_path))

    assert payload == {
        "coverage": [],
        "ok": False,
        "status": "failed",
        "violations": [
            _violation_entry("pkg.adapters"),
            _violation_entry("pkg.adapters.database"),
        ],
        "warnings": [
            _warning_entry("pkg.adapters"),
            _warning_entry("pkg.adapters.database"),
        ],
    }, f"the mixed JSON payload changed: {payload!r}"


def _warning_entry(imported: str) -> dict[str, object]:
    """Return the JSON entry a warned ``application`` edge writes."""
    return {
        "imported": imported,
        "imported_group": "adapter",
        "importer": "pkg.application.service",
        "importer_group": "application",
        "line": 1,
        "rule_id": "HEC001",
        "severity": "warning",
        "source_path": "<tmp>/pkg/application/service.py",
        "state": "warned",
    }


def _violation_entry(imported: str) -> dict[str, object]:
    """Return the JSON entry a forbidden ``domain`` edge writes."""
    return {
        "imported": imported,
        "imported_group": "adapter",
        "importer": "pkg.domain.model",
        "importer_group": "domain",
        "line": 1,
        "rule_id": "HEC001",
        "severity": "error",
        "source_path": "<tmp>/pkg/domain/model.py",
        "state": "forbidden",
    }
