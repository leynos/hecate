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

#: The warning every ``application`` edge writes, in text form. Both warned
#: imports name the adapter group, so the payload differs only by the dotted
#: target that the module barrel and the named symbol reach.
_WARNED_IMPORTS = ("pkg.adapters", "pkg.adapters.database")


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


def _expected_text(*, with_violation: bool, passed: bool) -> str:
    """Return the whole text document the fixture should render."""
    lines = []
    if with_violation:
        lines.extend(_violation_text(imported) for imported in _WARNED_IMPORTS)
    lines.extend(_warning_text(imported) for imported in _WARNED_IMPORTS)
    if passed:
        lines.insert(0, "hecate: architecture check passed")
    return "".join(line + "\n" for line in lines)


def _warning_text(imported: str) -> str:
    """Return the text line a warned ``application`` edge renders."""
    return (
        "HEC001 (warning): pkg.application.service:1 imports warning-level "
        f"module {imported} (application -> adapter)"
    )


def _violation_text(imported: str) -> str:
    """Return the text line a forbidden ``domain`` edge renders."""
    return (
        "HEC001: pkg.domain.model:1 imports forbidden module "
        f"{imported} (domain -> adapter)"
    )


def _expected_json(*, with_violation: bool, passed: bool) -> dict[str, object]:
    """Return the whole JSON payload the fixture should render."""
    return {
        "coverage": [],
        "ok": not with_violation,
        "status": "passed" if passed else "failed",
        "violations": (
            [_forbidden_entry(imported) for imported in _WARNED_IMPORTS]
            if with_violation
            else []
        ),
        "warnings": [_warned_entry(imported) for imported in _WARNED_IMPORTS],
    }


def _edge_entry(imported: str, *, warned: bool) -> dict[str, object]:
    """Return the JSON entry one diagnostic edge writes.

    The two kinds differ only in the groups they name and in the state and
    severity pair, so one builder keeps them from drifting apart as the
    payload grows.
    """
    importer, importer_group = (
        ("pkg.application.service", "application")
        if warned
        else ("pkg.domain.model", "domain")
    )
    state, severity = ("warned", "warning") if warned else ("forbidden", "error")
    return {
        "imported": imported,
        "imported_group": "adapter",
        "importer": importer,
        "importer_group": importer_group,
        "line": 1,
        "rule_id": "HEC001",
        "severity": severity,
        "source_path": f"<tmp>/{importer.replace('.', '/')}.py",
        "state": state,
    }


def _warned_entry(imported: str) -> dict[str, object]:
    """Return the JSON entry a warned ``application`` edge writes."""
    return _edge_entry(imported, warned=True)


def _forbidden_entry(imported: str) -> dict[str, object]:
    """Return the JSON entry a forbidden ``domain`` edge writes."""
    return _edge_entry(imported, warned=False)


def test_text_snapshot_of_a_warning_only_pass(tmp_path: Path) -> None:
    """A warning-only run passes and still names every warned edge."""
    result = _check(tmp_path, with_violation=False)

    text = _normalize(render_text(result, passed=True), tmp_path)

    assert text == _expected_text(with_violation=False, passed=True), (
        f"the warning-only text payload changed: {text!r}"
    )


def test_text_snapshot_of_an_enforced_warning_run(tmp_path: Path) -> None:
    """``--fail-on-warnings`` drops the pass notice but keeps the warnings."""
    result = _check(tmp_path, with_violation=False)

    text = _normalize(render_text(result, passed=False), tmp_path)

    assert text == _expected_text(with_violation=False, passed=False), (
        f"the enforced-warning text payload changed: {text!r}"
    )


def test_text_snapshot_of_a_mixed_warning_and_violation_run(
    tmp_path: Path,
) -> None:
    """Violations lead, warnings follow, and no pass notice is printed."""
    result = _check(tmp_path, with_violation=True)

    text = _normalize(render_text(result, passed=False), tmp_path)

    assert text == _expected_text(with_violation=True, passed=False), (
        f"the mixed text payload changed: {text!r}"
    )


def test_json_snapshot_of_a_warning_only_pass(tmp_path: Path) -> None:
    """JSON reports ``ok`` and ``status`` separately for a warning-only run."""
    result = _check(tmp_path, with_violation=False)

    payload = json.loads(_normalize(render_json(result, passed=True), tmp_path))

    assert payload == _expected_json(with_violation=False, passed=True), (
        f"the warning-only JSON payload changed: {payload!r}"
    )


def test_json_snapshot_of_an_enforced_warning_run(tmp_path: Path) -> None:
    """``ok`` keeps describing the architecture while ``status`` fails."""
    result = _check(tmp_path, with_violation=False)

    payload = json.loads(_normalize(render_json(result, passed=False), tmp_path))

    assert payload == _expected_json(with_violation=False, passed=False), (
        f"the enforced-warning JSON payload changed: {payload!r}"
    )


def test_json_snapshot_of_a_mixed_warning_and_violation_run(
    tmp_path: Path,
) -> None:
    """Both diagnostic kinds keep their own section and state."""
    result = _check(tmp_path, with_violation=True)

    payload = json.loads(_normalize(render_json(result, passed=False), tmp_path))

    assert payload == _expected_json(with_violation=True, passed=False), (
        f"the mixed JSON payload changed: {payload!r}"
    )
