"""Behavioural coverage for Makefile's blocking Skylos lint boundary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - invoke the fixed repository Makefile.
import sys
import typing as typ
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_SKYLOS_SCAN_ARGUMENTS: typ.Final[tuple[str, ...]] = (
    "--config-file",
    "pyproject.toml",
    "hecate",
    "--exclude",
    "tests",
    "--category",
    "dead_code",
    "--gate",
    "--format",
    "concise",
    "--no-upload",
    "--no-provenance",
    "--no-grep-verify",
)


def _write_executable(path: Path, source: str) -> Path:
    """Create a temporary executable used as an inert tool double."""
    path.write_text("#!" + sys.executable + "\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path


def test_make_lint_scans_with_skylos_and_propagates_a_scan_failure(
    tmp_path: Path,
) -> None:
    """The real lint target must forward scan policy and fail on Skylos errors."""
    make = shutil.which("make")
    assert make is not None, "Skylos lint behaviour test requires GNU Make"

    arguments_file = tmp_path / "skylos-arguments.json"
    skylos_recorder = _write_executable(
        tmp_path / "skylos-recorder",
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['SKYLOS_ARGUMENTS_FILE']).write_text(\n"
        "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
        ")\n"
        "raise SystemExit(19)\n",
    )
    uv_stub = _write_executable(tmp_path / "uv-stub", "raise SystemExit(0)\n")

    environment = dict(os.environ)
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        environment.pop(name, None)
    environment["SKYLOS_ARGUMENTS_FILE"] = str(arguments_file)

    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    pyproject_before = pyproject.read_bytes()
    command = (
        make,
        "--file",
        str(REPOSITORY_ROOT / "Makefile"),
        "-o",
        "build",
        f"UV={uv_stub}",
        f"SKYLOS_CLI={skylos_recorder}",
        "lint",
    )
    completed = subprocess.run(  # noqa: S603 - controlled local tool doubles.
        command,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        text=True,
    )

    assert arguments_file.is_file(), (
        "make lint must invoke the injected Skylos command recorder"
    )
    assert tuple(json.loads(arguments_file.read_text(encoding="utf-8"))) == (
        _EXPECTED_SKYLOS_SCAN_ARGUMENTS
    ), "make lint must forward the configured production-only strict scan arguments"
    assert completed.returncode != 0, (
        "make lint must fail when the Skylos scan returns a non-zero status"
    )
    assert pyproject.read_bytes() == pyproject_before, (
        "the isolated make lint behaviour test must not mutate Skylos configuration"
    )
