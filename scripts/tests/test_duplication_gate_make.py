"""Make-target contract tests for recording duplication exceptions."""

from __future__ import annotations

import dataclasses as dc
import shutil
import subprocess  # noqa: S404 - tests exercise the real Make target.
import sys
import typing as typ

import pytest
from duplication_gate_test_support import (
    REPOSITORY_ROOT,
    STUB_FAMILY,
    STUB_REPORT,
    allowlist,
    copied_gate_workspace,
    gate_environment,
    write_stub_nose,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


def _report_covering(*locations: tuple[str, str | None]) -> dict[str, object]:
    """Build a stub report whose single family spans exactly these locations.

    The `allow` command refuses a key set that does not cover a *whole* reported
    family, so each case below hands it the family those keys are meant to
    cover rather than one shape standing in for every case.
    """
    return {
        **STUB_REPORT,
        "families": [
            {
                **STUB_FAMILY,
                "locations": [
                    {"file": file, "start": 1, "end": 20, "name": name}
                    for file, name in locations
                ],
            }
        ],
    }


def _locations_covered_by(keys: tuple[str, ...]) -> tuple[tuple[str, str | None], ...]:
    """Return the stub locations that exactly these allow keys cover.

    A ``path::name`` key is met only by a location carrying that unit name, so
    deriving the report from the keys keeps the two consistent by construction
    and leaves the assertion about Make's argument forwarding as the thing
    under test.
    """
    return tuple(
        (path, name or None) for path, _, name in (key.partition("::") for key in keys)
    )


@dc.dataclass(frozen=True, slots=True)
class _MakeAllowRequest:
    """The `FIRST`, `SECOND`, and `REASON` inputs for one Make target run."""

    first: str | None
    second: str | None
    reason: str | None


def _make_allow(
    workspace: Path,
    *,
    request: _MakeAllowRequest,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real Make target against a copied, writable gate workspace."""
    make = shutil.which("make")
    assert make is not None, "Expected make to be available for contract tests."
    command = [
        make,
        "--no-print-directory",
        "-f",
        str(REPOSITORY_ROOT / "Makefile"),
        "duplication-allow",
        f"DUPLICATION_GATE={sys.executable} scripts/duplication_gate.py",
    ]
    if request.first is not None:
        command.append(f"FIRST={request.first}")
    if request.second is not None:
        command.append(f"SECOND={request.second}")
    if request.reason is not None:
        command.append(f"REASON={request.reason}")
    return subprocess.run(  # noqa: S603 - fixed Make target and copied workspace.
        command,
        cwd=workspace,
        env=gate_environment() if environment is None else environment,
        check=False,
        capture_output=True,
        text=True,
    )


class TestMakeDuplicationAllow:
    """The `make duplication-allow` command-line contract."""

    @pytest.mark.parametrize(
        ("first", "reason", "expected_error"),
        [
            pytest.param(None, "reviewed exception", "FIRST is required", id="first"),
            pytest.param("hecate/a.py", None, "REASON is required", id="reason"),
        ],
    )
    def test_make_duplication_allow_rejects_missing_and_ambient_values(
        self,
        tmp_path: Path,
        first: str | None,
        reason: str | None,
        expected_error: str,
    ) -> None:
        """Only command-line values satisfy the Make target's required inputs."""
        workspace, _script = copied_gate_workspace(tmp_path)
        environment = {
            **gate_environment(),
            "FIRST": "hecate/ambient.py",
            "SECOND": "hecate/ambient_second.py",
            "REASON": "ambient reason",
        }
        result = _make_allow(
            workspace,
            request=_MakeAllowRequest(first=first, second=None, reason=reason),
            environment=environment,
        )
        assert result.returncode == 2, result.stderr
        assert expected_error in result.stderr, (
            "Make must reject ambient values for required arguments."
        )

    @pytest.mark.parametrize(
        ("second", "expected_keys"),
        [
            pytest.param(None, ("hecate/a.py",), id="unit"),
            pytest.param(
                "hecate/b.py::beta",
                ("hecate/a.py", "hecate/b.py::beta"),
                id="members",
            ),
        ],
    )
    def test_make_duplication_allow_round_trips_quoted_values(
        self,
        tmp_path: Path,
        second: str | None,
        expected_keys: tuple[str, ...],
    ) -> None:
        """The Make target forwards unit and member inputs as literal arguments."""
        workspace, _script = copied_gate_workspace(tmp_path)
        keys = ("hecate/a.py",) if second is None else ("hecate/a.py", second)
        stub = write_stub_nose(
            tmp_path, report=_report_covering(*_locations_covered_by(keys))
        )
        marker = tmp_path / "injected-command"
        reason = f'kept literally: "$(touch {marker})"; $HOME'
        result = _make_allow(
            workspace,
            request=_MakeAllowRequest(
                first="hecate/a.py", second=second, reason=reason
            ),
            environment=gate_environment(NOSE_BIN=str(stub)),
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(workspace / "pyproject.toml")
        assert entries[0].keys == expected_keys, (
            "Make must forward the requested keys exactly."
        )
        assert entries[0].reason == reason, "Make must preserve quoted reasons."
        assert not marker.exists(), "Quoted values must not execute shell fragments."

    @pytest.mark.parametrize(
        ("template", "explanation"),
        [
            pytest.param(
                "hecate/`id>{0}`b.py",
                "A backtick substitution reaches the shell as written, because "
                "`make` has no reason to touch it.",
                id="backtick",
            ),
            pytest.param(
                "hecate/$(id>{0}).py",
                "A `$(...)` substitution survives `$(value ...)` unexpanded, "
                "which is precisely what leaves it live for the shell.",
                id="dollar-parens",
            ),
        ],
    )
    def test_make_duplication_allow_forwards_member_text_without_executing_it(
        self, tmp_path: Path, template: str, explanation: str
    ) -> None:
        """A member key is forwarded as data, never placed in the recipe as code.

        A key is structured into the recipe that runs the gate, so any command
        substitution it carries is executable text in that position: the
        substitution runs as the recipe does, and the key the gate receives is
        the substitution's result rather than the operator's own text. The
        assertion therefore has two halves -- nothing ran, *and* the recorded
        key is the one supplied -- because a recipe that executed the
        substitution while still forwarding the right key would be a different
        defect with the same first symptom.

        Both payloads redirect `id`'s output into the marker file rather than
        merely printing it, which is what makes the execution observable, and
        neither contains a space, which keeps this a test of *execution* rather
        than of word splitting. Splitting is a separate and documented limit of
        the interface, so a space-bearing payload here would fail for the wrong
        reason and hide the defect this case exists to catch.
        """
        workspace, _script = copied_gate_workspace(tmp_path)
        marker = tmp_path / "member-injection"
        key = template.format(marker)
        stub = write_stub_nose(
            tmp_path,
            report=_report_covering(("hecate/a.py", None), (key, None)),
        )
        result = _make_allow(
            workspace,
            request=_MakeAllowRequest(
                first="hecate/a.py", second=key, reason="reviewed exception"
            ),
            environment=gate_environment(NOSE_BIN=str(stub)),
        )

        assert not marker.exists(), (
            f"{explanation} The substitution ran, so `SECOND` reached the "
            "shell as code rather than as an argument."
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(workspace / "pyproject.toml")
        assert entries[0].keys == ("hecate/a.py", key), (
            "Make must record the member key the operator supplied, verbatim."
        )

    def test_make_duplication_allow_supports_repeated_members(
        self, tmp_path: Path
    ) -> None:
        """A family with three members is recorded through repeated `--second`."""
        workspace, _script = copied_gate_workspace(tmp_path)
        stub = write_stub_nose(
            tmp_path,
            report=_report_covering(
                ("hecate/a.py", None), ("hecate/b.py", None), ("hecate/c.py", None)
            ),
        )
        make = shutil.which("make")
        assert make is not None, "Expected make to be available for contract tests."
        result = subprocess.run(  # noqa: S603 - fixed target, copied workspace.
            [
                make,
                "--no-print-directory",
                "-f",
                str(REPOSITORY_ROOT / "Makefile"),
                "duplication-allow",
                f"DUPLICATION_GATE={sys.executable} scripts/duplication_gate.py",
                "FIRST=hecate/a.py",
                "SECOND=hecate/b.py",
                "SECOND+=hecate/c.py",
                "REASON=three parallel members",
            ],
            cwd=workspace,
            env=gate_environment(NOSE_BIN=str(stub)),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(workspace / "pyproject.toml")
        assert entries[0].keys == ("hecate/a.py", "hecate/b.py", "hecate/c.py"), (
            "Every member named on the command line must reach the entry."
        )


def _make_dry_run(target: str) -> subprocess.CompletedProcess[str]:
    """Expand a Make target's recipe without running it."""
    make = shutil.which("make")
    assert make is not None, "Expected make to be available for contract tests."
    return subprocess.run(  # noqa: S603 - fixed Make target in the repository root.
        [
            make,
            "--dry-run",
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            target,
        ],
        cwd=REPOSITORY_ROOT,
        env=gate_environment(),
        check=False,
        capture_output=True,
        text=True,
    )


class TestMakeGateWiring:
    """The Make targets that must run the blocking duplication gate.

    Mocked gate tests cannot show that `make lint` still reaches the gate, so
    these expand the real recipes and assert the gate command survives.
    """

    @pytest.mark.parametrize("target", ["lint", "duplication"])
    def test_target_runs_the_duplication_gate_check(self, target: str) -> None:
        """Both targets invoke the gate's `check` subcommand."""
        result = _make_dry_run(target)

        assert result.returncode == 0, result.stderr
        assert "scripts/duplication_gate.py check" in result.stdout, (
            f"`make {target}` must invoke the duplication gate's check command."
        )

    @pytest.mark.parametrize("target", ["lint", "duplication"])
    def test_target_pins_the_detector_binary(self, target: str) -> None:
        """Both targets pass the pinned detector location to the gate."""
        result = _make_dry_run(target)

        assert "NOSE_BIN=" in result.stdout, (
            f"`make {target}` must pin the detector binary for the gate."
        )

    def test_duplication_installs_the_pinned_detector_first(self) -> None:
        """The standalone target ensures the pinned detector before gating."""
        result = _make_dry_run("duplication")
        install = result.stdout.find("nose-cli@")
        check = result.stdout.find("scripts/duplication_gate.py check")

        assert install != -1, "`make duplication` must ensure the pinned detector."
        assert install < check, "The detector must be installed before the gate runs."
