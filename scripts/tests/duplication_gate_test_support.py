"""Shared fixtures for the duplication-gate tests.

The gate's own modules are imported here once so each test module can reach
them through this module, and the workspace builders below keep every test
that needs a real subprocess boundary off the network: a stub detector stands
in for the downloaded binary, and a copied workspace stands in for the
repository when a test must mutate configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - support invokes fixed test commands.
import sys
import typing as typ
from pathlib import Path

import atomic_write
import duplication_allowlist as allowlist
import duplication_gate as gate
import nose_detector as detector
import nose_schema as schema

if typ.TYPE_CHECKING:
    from collections import abc as cabc

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

GATE_MODULE_NAMES: typ.Final = (
    "atomic_write.py",
    "duplication_allowlist.py",
    "duplication_gate.py",
    "nose_detector.py",
    "nose_schema.py",
)

#: A ``[tool.nose]`` table the detector loader accepts. Tests that run the
#: real gate as a subprocess must write this into their copied workspace,
#: because the gate reads the settings from the configuration beside it rather
#: than from the repository it was copied out of.
NOSE_SETTINGS = """\
[tool.nose]
version = "0.20.0"
roots = ["hecate"]
mode = "syntax"
min-size = 24
surface = "all"
"""


class StubFamily(typ.TypedDict):
    """One stub duplication family with the report's own field names.

    The family is declared rather than left as an untyped literal so tests
    that derive a variant can subscript it: on a bare ``dict[str, object]``
    every lookup widens to ``object`` and the variant is rejected by the
    type checker before it ever runs.
    """

    id: str
    witness: str
    surface: str
    value: float
    metrics: dict[str, float]
    locations: list[dict[str, object]]


#: The one family every stub report starts from: two members, one per file.
STUB_FAMILY: StubFamily = {
    "id": "stub",
    "witness": "copy-paste",
    "surface": "default",
    "value": 22.1,
    "metrics": {"mean_score": 1.0},
    "locations": [
        {"file": "hecate/a.py", "start": 1, "end": 20, "name": None},
        {"file": "hecate/b.py", "start": 30, "end": 49, "name": None},
    ],
}

#: Report emitted by the stub detector: one two-member duplication family.
STUB_REPORT: dict[str, object] = {
    "schema_version": 9,
    "families": [STUB_FAMILY],
}


def copied_gate_workspace(
    tmp_path: Path, *, settings: str = NOSE_SETTINGS
) -> tuple[Path, Path]:
    """Create a mutable workspace holding the gate and its helper modules.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory to build the workspace inside.
    settings : str
        Configuration written into the copied workspace's ``pyproject.toml``.
        It defaults to a ``[tool.nose]`` table, because the gate command reads
        the detector settings from the configuration beside it: a copy that
        carries only a ``[project]`` table reaches the detector loader with no
        settings and is refused with a missing-version error rather than
        testing the command under test.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        The workspace root and the copied gate entry point inside it.
    """
    workspace = tmp_path / "gate-workspace"
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True)
    for name in GATE_MODULE_NAMES:
        shutil.copy(REPOSITORY_ROOT / "scripts" / name, scripts / name)
    (workspace / "pyproject.toml").write_text(
        f'[project]\nname = "gate-test"\nversion = "0"\n\n{settings}',
        encoding="utf-8",
    )
    return workspace, scripts / "duplication_gate.py"


def write_stub_nose(
    directory: Path,
    *,
    version: str = "nose 0.20.0",
    report: dict[str, object] | None = None,
) -> Path:
    """Write an executable stub standing in for the pinned nose binary.

    The stub answers ``--version`` and otherwise prints one canned JSON
    report, so gate tests exercise the real subprocess boundary without
    depending on a downloaded detector.

    Returns
    -------
    pathlib.Path
        Path to the executable stub.
    """
    stub = directory / "nose"
    payload = STUB_REPORT if report is None else report
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "if '--version' in sys.argv:\n"
        f"    print({version!r})\n"
        "    raise SystemExit(0)\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def gate_command(script: Path, *arguments: str) -> list[str]:
    """Build an isolated Python command for a copied gate script."""
    return [sys.executable, str(script), *arguments]


def gate_environment(**overrides: str) -> dict[str, str]:
    """Build a deterministic environment for gate subprocesses."""
    return {**os.environ, **overrides}


def run_gate_command(
    script: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a copied gate command and capture its completed result."""
    return subprocess.run(  # noqa: S603 - fixed test interpreter and copied script.
        gate_command(script, *arguments),
        cwd=script.parent.parent,
        env=gate_environment() if environment is None else environment,
        check=False,
        capture_output=True,
        text=True,
    )


def stub_settings() -> detector.NoseSettings:
    """Build the detector settings shared by the gate tests.

    Vary individual fields at the call site with :func:`dataclasses.replace`
    rather than threading an override parameter per field through this factory.

    Returns
    -------
    detector.NoseSettings
        The pinned version, roots, channels, size floor, surface, ranking
        bound, and exclusions shared by the gate tests.
    """
    return detector.NoseSettings(
        version="0.20.0",
        roots=("hecate",),
        mode="syntax,semantic,near",
        min_size=24,
        surface="all",
        top=30,
        exclude=(),
    )


def stub_runner(
    *, version: str = "nose 0.20.0", report: object = None
) -> detector.CommandRunner:
    """Build a command runner double answering version and query commands."""

    def run(command: cabc.Sequence[str]) -> str:
        if "--version" in command:
            return f"{version}\n"
        return json.dumps(STUB_REPORT if report is None else report)

    return run


__all__ = [
    "GATE_MODULE_NAMES",
    "NOSE_SETTINGS",
    "REPOSITORY_ROOT",
    "STUB_FAMILY",
    "STUB_REPORT",
    "StubFamily",
    "allowlist",
    "atomic_write",
    "copied_gate_workspace",
    "detector",
    "gate",
    "gate_command",
    "gate_environment",
    "run_gate_command",
    "schema",
    "stub_runner",
    "stub_settings",
    "write_stub_nose",
]
