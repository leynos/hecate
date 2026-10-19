"""Real-boundary tests for the duplication gate.

Every test here crosses a process boundary that the in-process seam tests in
``test_duplication_gate_commands.py`` deliberately replace: either the gate
runs as a subprocess through its own CLI, or the pinned ``nose`` binary runs
for real. That is why they live apart -- they answer a different question
("does the shipped entry point work?") from the seam tests ("does this unit
translate its inputs correctly?"), and they are the only tests that can catch
a defect in argument parsing or in the copied gate's own configuration.
"""

from __future__ import annotations

import dataclasses as dc
import json
import subprocess  # noqa: S404 - tests exercise real gate and detector commands.
import sys
import textwrap
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    REPOSITORY_ROOT,
    STUB_FAMILY,
    STUB_REPORT,
    allowlist,
    copied_gate_workspace,
    detector,
    gate_environment,
    run_gate_command,
    write_stub_nose,
)


def _report_with_named_locations(*names: str) -> dict[str, object]:
    """Build a stub report whose first family names the given units.

    Both locations are placed on the same file so that a family can be covered
    by ``path::name`` keys alone; the shared file is what distinguishes a
    single-key ``unit`` entry from a cross-file ``members`` entry.
    """
    return {
        **STUB_REPORT,
        "families": [
            {
                **STUB_FAMILY,
                "locations": [
                    {"file": "hecate/b.py", "start": 1, "end": 20, "name": name}
                    for name in names
                ],
            }
        ],
    }


def _resolved_binary_or_skip() -> str:
    """Return the pinned detector path, skipping when it is not installed."""
    settings = detector.load_settings(REPOSITORY_ROOT / "pyproject.toml")
    try:
        return detector.resolve_binary(settings)
    except detector.GateExecutionError as error:  # pragma: no cover
        pytest.skip(str(error))


class TestAllowCli:
    """`allow` driven through the gate's own command line."""

    def test_allow_cli_round_trips_a_unit_key(self, tmp_path: Path) -> None:
        """A single named unit covering its whole family is recorded as ``unit``."""
        _workspace, script = copied_gate_workspace(tmp_path)
        stub = write_stub_nose(
            tmp_path, report=_report_with_named_locations("beta", "gamma")
        )
        result = run_gate_command(
            script,
            "allow",
            "--first",
            "hecate/b.py::beta",
            "--second",
            "hecate/b.py::gamma",
            "--reason",
            "reviewed exception",
            environment=gate_environment(NOSE_BIN=str(stub)),
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(script.parent.parent / "pyproject.toml")
        assert entries[0].keys == ("hecate/b.py::beta", "hecate/b.py::gamma"), (
            "CLI must retain its requested keys."
        )
        assert entries[0].reason == "reviewed exception", (
            "CLI must retain the supplied reason."
        )

    def test_allow_cli_round_trips_members(self, tmp_path: Path) -> None:
        """A cross-file family is recorded as ``members`` and then silences it."""
        _workspace, script = copied_gate_workspace(tmp_path)
        stub = write_stub_nose(tmp_path)

        result = run_gate_command(
            script,
            "allow",
            "--first",
            "hecate/a.py",
            "--second",
            "hecate/b.py",
            "--reason",
            "reviewed exception",
            environment=gate_environment(NOSE_BIN=str(stub)),
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(script.parent.parent / "pyproject.toml")
        assert entries[0].keys == ("hecate/a.py", "hecate/b.py"), (
            "CLI must retain its requested keys."
        )
        assert entries[0].reason == "reviewed exception", (
            "CLI must retain the supplied reason."
        )

        checked = run_gate_command(
            script, "check", environment=gate_environment(NOSE_BIN=str(stub))
        )
        assert checked.returncode == 0, checked.stderr
        assert "duplication gate passed" in checked.stdout, (
            "The recorded exception must silence the family it covers."
        )


class TestCheckCli:
    """`check` driven through the gate's own command line."""

    def test_check_cli_passes_with_a_stub_detector(self, tmp_path: Path) -> None:
        """The gate exits zero through its real CLI when every family is allowed."""
        workspace, script = copied_gate_workspace(tmp_path)
        stub = write_stub_nose(tmp_path)
        (workspace / "pyproject.toml").write_text(
            textwrap.dedent(
                """\
                [tool.nose]
                version = "0.20.0"
                roots = ["hecate"]
                mode = "syntax"
                min-size = 24
                surface = "all"

                [[tool.duplication_gate.allow]]
                members = ["hecate/a.py", "hecate/b.py"]
                reason = "parallel wire contracts"
                """
            ),
            encoding="utf-8",
        )
        result = run_gate_command(
            script,
            "check",
            environment=gate_environment(NOSE_BIN=str(stub)),
        )
        assert result.returncode == 0, result.stderr
        assert "duplication gate passed" in result.stdout, (
            "An allowed family must leave the gate passing."
        )

    def test_real_check_cli_passes(self) -> None:
        """The checked-in gate runs successfully through its real CLI boundary."""
        _resolved_binary_or_skip()
        result = subprocess.run(  # noqa: S603 - fixed repository gate command.
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "duplication_gate.py"),
                "check",
            ],
            cwd=REPOSITORY_ROOT,
            env=gate_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "duplication gate passed" in result.stdout, (
            "Real check invocation must report its successful gate result."
        )


class TestPinnedDetector:
    """The pinned detector's own boundary, without the gate in between."""

    def test_reports_a_planted_verbatim_copy(self, tmp_path: Path) -> None:
        """The pinned detector reports a planted copy through normalization."""
        settings = detector.load_settings(REPOSITORY_ROOT / "pyproject.toml")
        binary = _resolved_binary_or_skip()
        body = textwrap.dedent(
            """\
            def NAME(items):
                total = 0.0
                for item in items:
                    price = item["price"] * item["quantity"]
                    if item.get("taxable"):
                        price *= 1.2
                    if item.get("discount"):
                        price -= item["discount"]
                    total += price
                if total < 0:
                    total = 0.0
                return round(total, 2)
            """
        )
        workspace = tmp_path
        (workspace / "mod.py").write_text(
            body.replace("NAME", "first_total")
            + "\n\n"
            + body.replace("NAME", "second_total"),
            encoding="utf-8",
        )
        command = detector.build_command(
            binary, dc.replace(settings, roots=(".",), min_size=8)
        )
        result = subprocess.run(  # noqa: S603 - pinned, repository-owned binary.
            command,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        findings = detector.normalize_findings(json.loads(result.stdout))
        assert findings, "The planted copy must be reported."
        assert any(
            {location.name for location in finding.locations}
            == {"first_total", "second_total"}
            for finding in findings
        ), "The planted copy must name both duplicated functions."


class TestEndToEndBlocking:
    """The real detector driving the real `check` command.

    Every other blocking test substitutes a stub report or calls the detector
    without the gate, so none of them shows that a genuine duplicate reaches
    `check` and fails the build. These do, using the pinned binary.
    """

    DUPLICATE_BODY = textwrap.dedent(
        """\
        def NAME(items):
            total = 0.0
            for item in items:
                price = item["price"] * item["quantity"]
                if item.get("taxable"):
                    price *= 1.2
                if item.get("discount"):
                    price -= item["discount"]
                total += price
            if total < 0:
                total = 0.0
            return round(total, 2)
        """
    )

    def _planted_workspace(self, tmp_path: Path, *, allow: str = "") -> Path:
        """Build a gate workspace whose package holds one verbatim duplicate."""
        workspace, _script = copied_gate_workspace(tmp_path)
        package = workspace / "planted"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "mod.py").write_text(
            self.DUPLICATE_BODY.replace("NAME", "first_total")
            + "\n\n"
            + self.DUPLICATE_BODY.replace("NAME", "second_total"),
            encoding="utf-8",
        )
        (workspace / "pyproject.toml").write_text(
            textwrap.dedent(
                """\
                [project]
                name = "gate-test"
                version = "0"

                [tool.nose]
                version = "0.20.0"
                roots = ["planted"]
                mode = "syntax,semantic,near"
                min-size = 8
                surface = "all"
                top = 30
                """
            )
            + allow,
            encoding="utf-8",
        )
        return workspace

    def _run_check(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        """Run the copied gate's real `check` against the pinned detector."""
        return run_gate_command(
            workspace / "scripts" / "duplication_gate.py",
            "check",
            environment=gate_environment(NOSE_BIN=_resolved_binary_or_skip()),
        )

    def test_planted_duplicate_blocks_the_gate(self, tmp_path: Path) -> None:
        """A genuine duplicate fails `check` and names both copies."""
        result = self._run_check(self._planted_workspace(tmp_path))

        assert result.returncode == 1, (
            f"A planted duplicate must fail the gate.\n{result.stdout}{result.stderr}"
        )
        assert "planted/mod.py" in result.stdout, (
            "The report must locate the duplicated file."
        )
        assert "make duplication-allow" in result.stdout, (
            "A blocking report must show how to record a reasoned exception."
        )

    def test_reasoned_exception_unblocks_the_planted_duplicate(
        self, tmp_path: Path
    ) -> None:
        """The same duplicate passes once a reasoned allow entry covers it."""
        allow = textwrap.dedent(
            """
            [[tool.duplication_gate.allow]]
            unit = "planted/mod.py"
            reason = "Planted fixture proving the gate blocks and allows."
            """
        )
        result = self._run_check(self._planted_workspace(tmp_path, allow=allow))

        assert result.returncode == 0, (
            f"A covered duplicate must pass.\n{result.stdout}{result.stderr}"
        )
        assert "duplication gate passed" in result.stdout, (
            "The gate must report its successful result."
        )

    def test_an_out_of_scope_member_makes_the_family_block_again(
        self, tmp_path: Path
    ) -> None:
        """A third copy outside the exception's keys must fail the gate again."""
        workspace = self._planted_workspace(tmp_path)
        allow = textwrap.dedent(
            """
            [[tool.duplication_gate.allow]]
            unit = "planted/mod.py"
            reason = "Planted fixture proving the gate blocks and allows."
            """
        )
        (workspace / "pyproject.toml").write_text(
            (workspace / "pyproject.toml").read_text(encoding="utf-8") + allow,
            encoding="utf-8",
        )
        # The third copy lands in a file the exception does not name, so the
        # family's coverage is no longer complete.
        (workspace / "planted" / "extra.py").write_text(
            self.DUPLICATE_BODY.replace("NAME", "third_total"),
            encoding="utf-8",
        )

        result = self._run_check(workspace)

        assert result.returncode == 1, (
            "A family reaching a new file must block again.\n"
            f"{result.stdout}{result.stderr}"
        )
        assert "planted/extra.py" in result.stdout, (
            "The report must name the newly duplicated file."
        )
