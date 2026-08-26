"""Behavioural contracts for the non-mutating Skylos allow-list helper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - contract tests invoke fixed local tools.
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import hypothesis as hyp
import hypothesis.strategies as st
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_MAKE_EXECUTABLE = shutil.which("make")
_SHELL_SIGNIFICANT_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$;|&'\"()[]{}*?!\\`"
)


def _surround_with_optional_whitespace(prefix: str, content: str, suffix: str) -> str:
    """Construct a non-empty shell-significant value with retained whitespace."""
    return prefix + content + suffix


_SHELL_ARGUMENT_TEXT = st.builds(
    _surround_with_optional_whitespace,
    st.text(alphabet=" \t", max_size=4),
    st.text(alphabet=_SHELL_SIGNIFICANT_ALPHABET, min_size=1, max_size=40),
    st.text(alphabet=" \t", max_size=4),
)


def _make_executable() -> str:
    """Return the Make executable needed to exercise the helper boundary."""
    assert _MAKE_EXECUTABLE is not None, "Skylos allow-list contracts require make"
    return _MAKE_EXECUTABLE


def _run_skylos_allow(
    *,
    variables: dict[str, str],
    skylos_cli: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the helper with environment-provided caller values."""
    environment = dict(os.environ)
    for name in ("REASON", "SKYLOS_CLI", "SKYLOS_RECORDER_OUTPUT", "SYMBOL"):
        environment.pop(name, None)
    environment["NAME"] = "wsl-hostname"
    environment.update(variables)

    command = [_make_executable(), "skylos-allow"]
    if skylos_cli is not None:
        command.append(f"SKYLOS_CLI={skylos_cli}")
    return subprocess.run(  # noqa: S603 - fixed Make target and controlled test inputs.
        command,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
    )


def _write_recorder(directory: Path) -> tuple[Path, Path]:
    """Create an executable that serializes the CLI arguments it receives."""
    recorder = directory / "record_skylos_arguments.py"
    output = directory / "arguments.json"
    recorder.write_text(
        "#!" + sys.executable + "\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['SKYLOS_RECORDER_OUTPUT']).write_text(\n"
        "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )
    recorder.chmod(0o700)
    return recorder, output


@pytest.mark.parametrize(
    ("variables", "missing_name"),
    [
        ({"REASON": "verified runtime caller"}, "SYMBOL"),
        ({"SYMBOL": "handler"}, "REASON"),
        ({"SYMBOL": " \t", "REASON": "verified runtime caller"}, "SYMBOL"),
        ({"SYMBOL": "handler", "REASON": " \t"}, "REASON"),
    ],
    ids=("missing-symbol", "missing-reason", "blank-symbol", "blank-reason"),
)
def test_skylos_allow_rejects_missing_or_whitespace_values(
    variables: dict[str, str], missing_name: str, tmp_path: Path
) -> None:
    """The helper must reject invalid values despite WSL's injected `NAME`."""
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    before = pyproject.read_bytes()
    recorder, output = _write_recorder(tmp_path)

    completed = _run_skylos_allow(
        variables={**variables, "SKYLOS_RECORDER_OUTPUT": str(output)},
        skylos_cli=str(recorder),
    )

    assert completed.returncode == 2, (
        f"Skylos allow-list helper must reject a missing {missing_name} with exit 2"
    )
    assert (
        f"Error: {missing_name} is required for a named whitelist exception"
        in completed.stderr
    ), f"Skylos allow-list helper must identify the missing {missing_name}"
    assert not output.exists(), (
        "Skylos allow-list helper must reject invalid input before invoking Skylos"
    )
    assert pyproject.read_bytes() == before, (
        "Skylos allow-list validation must not mutate pyproject.toml"
    )


@hyp.settings(max_examples=20, deadline=None)
@hyp.example(symbol=" $(handler);* ", reason=' Loaded "$plugin" | registry ')
@hyp.given(symbol=_SHELL_ARGUMENT_TEXT, reason=_SHELL_ARGUMENT_TEXT)
def test_skylos_allow_forwards_exact_environment_values(
    symbol: str, reason: str
) -> None:
    """Quoted Make exports must preserve one exact argument for each value."""
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    before = pyproject.read_bytes()
    with TemporaryDirectory(prefix="hecate-skylos-") as temporary_directory:
        recorder, output = _write_recorder(Path(temporary_directory))
        completed = _run_skylos_allow(
            variables={
                "REASON": reason,
                "SKYLOS_RECORDER_OUTPUT": str(output),
                "SYMBOL": symbol,
            },
            skylos_cli=str(recorder),
        )

        assert completed.returncode == 0, (
            "Skylos allow-list helper must accept non-empty SYMBOL and REASON"
        )
        assert output.exists(), (
            "Skylos allow-list helper must invoke the injected SKYLOS_CLI recorder"
        )
        assert json.loads(output.read_text(encoding="utf-8")) == [
            "whitelist",
            symbol,
            "--reason",
            reason,
        ], "Skylos allow-list helper must preserve exact whitelist argv boundaries"
    assert pyproject.read_bytes() == before, (
        "Injected Skylos recorder tests must not mutate pyproject.toml"
    )
