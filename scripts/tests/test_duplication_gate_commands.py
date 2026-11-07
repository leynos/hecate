"""Command behaviour tests for the duplication gate.

These drive `check` and `allow` in process, replacing the two seams that reach
outside the interpreter -- the allowlist reader and the detector -- with
doubles. Tests that must cross a real process boundary live in
``test_duplication_gate_cli.py`` instead, so the split is by boundary rather
than by size.
"""

from __future__ import annotations

import dataclasses as dc
import tomllib
from collections import abc as cabc
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    STUB_REPORT,
    allowlist,
    detector,
    gate,
    write_stub_nose,
)


@dc.dataclass(frozen=True, slots=True)
class _RefusedKey:
    """One key set the allow command must refuse, and why it must."""

    first: str
    expected: str
    explanation: str


@dc.dataclass(frozen=True, slots=True)
class _MalformedContainer:
    """One wrongly typed container, and the diagnostic it must draw.

    The four containers nest inside one another, so a case names the exact
    message rather than a shared prefix: a validator that blamed the wrong
    level would still say "configuration error" while sending the operator to
    the wrong line of the file.
    """

    document: str
    message: str


def _finding() -> detector.Finding:
    """Build a representative blocking finding."""
    return detector.Finding(
        witness="copy-paste",
        value=22.1,
        locations=(
            detector.Location(file="hecate/a.py", start=1, end=20, name=None),
            detector.Location(file="hecate/b.py", start=30, end=49, name="beta"),
        ),
    )


def _double[T](result: T | Exception) -> cabc.Callable[..., T]:
    """Build a dependency double that either returns ``result`` or raises it.

    The two seams call their dependency with different signatures, and the
    gate's own wrappers add arguments of their own, so the double accepts
    anything and lets each call site exercise its own shape.
    """

    def run(*_args: object, **_kwargs: object) -> T:
        """Return ``result``, or raise it when it is an exception."""
        if isinstance(result, Exception):
            raise result
        return result

    return run


class TestCheckCommand:
    """`check` orchestration through its replaced seams."""

    def test_check_reports_blocking_findings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The check command emits the blocking report and status one."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        monkeypatch.setattr(gate, "detect_findings", _double([_finding()]))
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 1, "Blocking findings must return status one."
        assert capsys.readouterr().out == (
            "duplicate code: 1 unsuppressed family/families\n"
            "  hecate/a.py:1-20 ~ hecate/b.py:30-49 beta (copy-paste, value 22.1)\n"
            "Extract the shared logic into one helper, or record a considered "
            "exception:\n"
            "  make duplication-allow FIRST='<path[::name]>' "
            "[SECOND='<path[::name]>'] REASON='<why this stays>'\n"
        ), "Blocking report must remain actionable and deterministic."

    def test_check_reports_stale_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Allow entries covering nothing are reported as unmatched in this scan."""
        monkeypatch.chdir(tmp_path)
        entry = allowlist.AllowEntry(keys=("hecate/gone.py",), reason="resolved")
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: (entry,))
        monkeypatch.setattr(gate, "detect_findings", _double([]))
        gate.check()
        assert capsys.readouterr().out == (
            "stale allow entry (hecate/gone.py): unmatched in this scan; "
            "widen the scan (raise `top`, or lower `min-size`) before deleting "
            "the entry, because the duplication it silenced may be gone, or its "
            "family may have changed shape\n"
            "duplication gate passed\n"
        ), "Stale entries must be reported alongside a passing gate."

    def test_stale_entry_does_not_claim_the_duplication_is_gone(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An entry can go stale because its family gained an uncovered member.

        That case is the dangerous one: the duplication is still present, and
        the entry is needed as the starting point for extending it. A
        diagnostic that says the duplication is gone invites deleting the
        entry instead, so the wording is checked for the weaker, true claim
        and for the widening step that would tell them apart.
        """
        monkeypatch.chdir(tmp_path)
        entry = allowlist.AllowEntry(
            keys=("hecate/a.py", "hecate/b.py"), reason="two-member parallel"
        )
        grown = detector.Finding(
            witness="copy-paste",
            value=80.0,
            locations=(
                detector.Location(file="hecate/a.py", start=1, end=20, name=None),
                detector.Location(file="hecate/b.py", start=30, end=49, name=None),
                detector.Location(file="hecate/c.py", start=1, end=20, name=None),
            ),
        )
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: (entry,))
        monkeypatch.setattr(gate, "detect_findings", _double([grown]))
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 1, "A grown family must still block."
        output = capsys.readouterr().out
        assert "hecate/a.py ~ hecate/b.py" in output, (
            "The stale entry must be identified by its keys."
        )
        assert "hecate/c.py" in output, (
            "The blocking report must name the member outside the entry's keys."
        )
        assert "unmatched in this scan" in output, (
            "A stale entry must be described as unmatched in this scan, which "
            "is what the gate actually observed."
        )
        assert "before deleting the entry" in output, (
            "The diagnostic must require a widened scan before deletion."
        )
        assert "the duplication is gone\n" not in output, (
            "A stale entry must not assert the duplication is gone; in this "
            "case it grew an uncovered member and still blocks."
        )

    @pytest.mark.parametrize(
        ("failing_seam", "error"),
        [
            pytest.param(
                "allowlist",
                OSError("unreadable configuration"),
                id="allowlist-io",
            ),
            pytest.param(
                "detector",
                OSError("detector executable unavailable"),
                id="detector-io",
            ),
        ],
    )
    def test_check_inputs_wrap_environment_failures(
        self, failing_seam: str, error: Exception
    ) -> None:
        """Injected reader and detector failures become explicit gate errors."""
        reader = _double(error if failing_seam == "allowlist" else ())
        detect = _double(error if failing_seam == "detector" else [])

        with pytest.raises(gate.GateExecutionError, match=str(error)):
            gate._check_inputs(allowlist_reader=reader, detector=detect)

    def test_check_reports_detector_schema_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed detector reports exit cleanly instead of showing a traceback."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        monkeypatch.setattr(
            gate,
            "detect_findings",
            _double(TypeError("nose report families must be an array")),
        )
        with pytest.raises(SystemExit) as error:
            gate.check()

        assert error.value.code == 2, "Malformed detector reports must return two."
        assert capsys.readouterr().err == (
            "configuration error: nose report families must be an array\n"
        ), "Schema errors must use the configuration diagnostic."
        assert Path.cwd() == tmp_path, (
            "The check command must not change its caller's working directory."
        )

    def test_check_reports_a_version_mismatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unpinned detector fails the gate with a remediation message."""
        workspace = tmp_path
        stub = write_stub_nose(workspace, version="nose 0.19.0")
        monkeypatch.setenv("NOSE_BIN", str(stub))
        monkeypatch.chdir(workspace)
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 2, "A version mismatch must return two."
        assert "make install-nose" in capsys.readouterr().err, (
            "The mismatch diagnostic must name the install remediation."
        )


class TestAllowCommand:
    """`allow` orchestration through its replaced seams."""

    def _stub_detector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make the allow command see the shared two-member stub family."""
        monkeypatch.setattr(
            gate,
            "detect_findings",
            _double(detector.normalize_findings(STUB_REPORT)),
        )

    def test_allow_refuses_a_blank_reason(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An empty reason is refused before the detector is consulted.

        The refusal is about the operator's command, not about the repository,
        so it must not depend on a bandit or detector run whose failure would
        mask it, and it must not be reported as a fault in the configuration
        file the command was asked to update.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)
        monkeypatch.setattr(
            gate,
            "detect_findings",
            _double(AssertionError("the detector must not run for a blank reason")),
        )

        with pytest.raises(SystemExit) as error:
            gate.allow(first="hecate/a.py", reason="   ")

        assert error.value.code == 2, "A blank reason must return two."
        assert capsys.readouterr().err == "REASON must not be empty\n", (
            "The blank-reason diagnostic is about the command, so it carries no "
            "file label."
        )
        assert pyproject.read_text(encoding="utf-8") == "[project]\nname = 'x'\n", (
            "A refused command must not rewrite the manifest."
        )

    def test_allow_reports_malformed_existing_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed existing allows exit cleanly instead of showing a traceback."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[[tool.duplication_gate.allow]]\nunit = "hecate/a.py"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)
        self._stub_detector(monkeypatch)

        with pytest.raises(SystemExit) as error:
            gate.allow(
                first="hecate/a.py",
                second=["hecate/b.py"],
                reason="reviewed exception",
            )

        assert error.value.code == 2, "Malformed existing allows must return two."
        assert capsys.readouterr().err == (
            "configuration error: duplication_gate.allow[0] "
            "requires a non-empty reason\n"
        ), "Malformed allows must use the configuration diagnostic."

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param(
                _MalformedContainer(
                    document="tool = 1\n\n[project]\nname = 'x'\n",
                    message="pyproject.tool must be a table with string keys",
                ),
                id="scalar-tool-table",
            ),
            pytest.param(
                _MalformedContainer(
                    document="[project]\nname = 'x'\n\n[tool]\nduplication_gate = 1\n",
                    message=(
                        "pyproject.tool.duplication_gate must be a table with "
                        "string keys"
                    ),
                ),
                id="scalar-gate-table",
            ),
            pytest.param(
                _MalformedContainer(
                    document=(
                        "[project]\nname = 'x'\n\n[tool.duplication_gate]\nallow = 3\n"
                    ),
                    message=(
                        "pyproject.tool.duplication_gate.allow must be an array of "
                        "tables"
                    ),
                ),
                id="scalar-allow-array",
            ),
            pytest.param(
                _MalformedContainer(
                    document=(
                        "[project]\nname = 'x'\n\n[tool.duplication_gate]\n"
                        'allow = "nope"\n'
                    ),
                    message=(
                        "pyproject.tool.duplication_gate.allow must be an array of "
                        "tables"
                    ),
                ),
                id="string-allow-array",
            ),
        ],
    )
    def test_allow_reports_malformed_parent_containers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        case: _MalformedContainer,
    ) -> None:
        """A wrongly typed container is a configuration error, not a traceback.

        A malformed *entry* is already reported, but a malformed *container*
        reaches `append` with a scalar where a table belongs. That is the case
        a half-edited manifest actually produces: someone types
        `duplication_gate = 1` above the entries, or replaces the array of
        tables with a string. Without validation the fault surfaces as an
        `AttributeError` from `setdefault` or a `TypeError` from iteration --
        a traceback rather than the gate's own diagnostic, and a failure mode
        that looks like a crash in the gate instead of a fault in the file.

        The document must also survive: a rejected manifest is never rewritten,
        so the operator's next step is to fix the line they just typed.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(case.document, encoding="utf-8")
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)
        self._stub_detector(monkeypatch)

        with pytest.raises(SystemExit) as error:
            gate.allow(
                first="hecate/a.py",
                second=["hecate/b.py"],
                reason="reviewed exception",
            )

        assert error.value.code == 2, "A malformed container must return two."
        assert capsys.readouterr().err == f"configuration error: {case.message}\n", (
            "A malformed container must name the container at fault."
        )
        assert pyproject.read_text(encoding="utf-8") == case.document, (
            "A rejected document must be left exactly as it was found."
        )

    def test_allow_reports_write_failures(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A filesystem failure while recording an allow exits cleanly."""
        monkeypatch.setattr(
            gate, "append_allow_entry", _double(OSError("read-only filesystem"))
        )
        self._stub_detector(monkeypatch)

        with pytest.raises(SystemExit) as exit_error:
            gate.allow(
                first="hecate/a.py",
                second=["hecate/b.py"],
                reason="reviewed exception",
            )

        assert exit_error.value.code == 2, "Write failures must return two."
        assert capsys.readouterr().err == (
            "configuration error: read-only filesystem\n"
        ), "Write failures must use the configuration diagnostic."

    def test_allow_labels_a_detector_failure_as_a_tool_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A detector failure must not send the operator to ``pyproject.toml``.

        ``GateExecutionError`` reports a provisioning fault -- a missing or
        unpinned binary, a timeout, a non-zero exit -- and labels itself
        accordingly. Replacing that label with the configuration one would tell
        an operator to look for a fault in the file they just asked the gate to
        update, while the actual repair is ``make install-nose``.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)
        monkeypatch.setattr(
            gate, "detect_findings", _double(detector.GateExecutionError("gone"))
        )

        with pytest.raises(SystemExit) as exit_error:
            gate.allow(
                first="hecate/a.py",
                second=["hecate/b.py"],
                reason="reviewed exception",
            )

        assert exit_error.value.code == 2, "A tool failure must return two."
        assert capsys.readouterr().err == "tool error: gone\n", (
            "A detector failure must keep the label its error defines."
        )

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param(
                _RefusedKey(
                    first="/hecate/a.py",
                    expected="repository-relative",
                    explanation="An absolute key names no repository file.",
                ),
                id="absolute-key",
            ),
            pytest.param(
                _RefusedKey(
                    first="hecate/typo.py",
                    expected="covers no reported family",
                    explanation="A key the detector never reports matches nothing.",
                ),
                id="unreported-file",
            ),
            pytest.param(
                _RefusedKey(
                    first="hecate/a.py",
                    expected="covers no reported family",
                    explanation=(
                        "Keys reaching only one member of a family are not an "
                        "exception."
                    ),
                ),
                id="partial-coverage",
            ),
        ],
    )
    def test_allow_refuses_keys_that_form_no_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        case: _RefusedKey,
    ) -> None:
        """An unusable key set exits with a diagnostic and records nothing.

        Partial coverage is the more dangerous refusal: a partial key set is
        syntactically perfect and names a real file, so without the coverage
        check it would be recorded, reported as a success, and then ignored by
        the gate -- which goes on blocking while the allowlist looks fixed.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)
        self._stub_detector(monkeypatch)

        with pytest.raises(SystemExit) as error:
            gate.allow(first=case.first, reason="reviewed exception")

        assert error.value.code == 2, f"{case.explanation} This must return two."
        assert case.expected in capsys.readouterr().err, (
            f"{case.explanation} The diagnostic must say as much."
        )
        assert "duplication_gate" not in pyproject.read_text(encoding="utf-8"), (
            "A refused key must not be recorded."
        )


class TestRecordAllowEntry:
    """The allow use case, driven entirely through injected dependencies.

    The command tests above replace module globals, which proves the CLI is
    wired but not that the use case can be exercised without a process-wide
    seam. These drive the same behaviour through arguments alone.
    """

    def test_records_an_entry_covering_a_reported_family(self, tmp_path: Path) -> None:
        """A covering key set reaches the writer with the caller's arguments."""
        pyproject = tmp_path / "pyproject.toml"
        recorded: list[tuple[Path, tuple[str, ...], str]] = []

        def writer(path: Path, *, keys: cabc.Sequence[str], reason: str) -> None:
            """Record the path, keys and reason rather than writing the entry."""
            recorded.append((path, tuple(keys), reason))

        outcome = gate.record_allow_entry(
            ("hecate/a.py", "hecate/b.py"),
            "reviewed exception",
            gate.AllowDependencies(
                detector=_double(detector.normalize_findings(STUB_REPORT)),
                pyproject_path=pyproject,
                writer=writer,
            ),
        )

        assert outcome == gate.AllowOutcome(keys=("hecate/a.py", "hecate/b.py")), (
            "The outcome must report the keys the caller supplied."
        )
        assert recorded == [
            (pyproject, ("hecate/a.py", "hecate/b.py"), "reviewed exception")
        ], "The writer must receive the destination, keys and reason unchanged."

    def test_consults_the_injected_detector(self, tmp_path: Path) -> None:
        """Coverage is decided by the supplied detector, not a module global."""
        calls: list[int] = []

        def detector_seam() -> list[detector.Finding]:
            """Count the call and return the findings from the stub report."""
            calls.append(1)
            return detector.normalize_findings(STUB_REPORT)

        gate.record_allow_entry(
            ("hecate/a.py", "hecate/b.py"),
            "reviewed",
            gate.AllowDependencies(
                detector=detector_seam,
                pyproject_path=tmp_path / "pyproject.toml",
                writer=_double(None),
            ),
        )

        assert calls == [1], "The injected detector must be the one consulted."

    def test_refuses_a_key_set_covering_no_family(self, tmp_path: Path) -> None:
        """A refused key set is diagnosed and never reaches the writer."""
        recorded: list[object] = []

        def writer(path: Path, *, keys: cabc.Sequence[str], reason: str) -> None:
            """Record the path of any write, which this case must never reach."""
            recorded.append(path)

        with pytest.raises(gate.GateConfigError, match="covers no reported family"):
            gate.record_allow_entry(
                ("hecate/typo.py",),
                "reviewed",
                gate.AllowDependencies(
                    detector=_double(detector.normalize_findings(STUB_REPORT)),
                    pyproject_path=tmp_path / "pyproject.toml",
                    writer=writer,
                ),
            )

        assert recorded == [], "A refused key must not be written."

    def test_translates_a_writer_fault(self, tmp_path: Path) -> None:
        """A filesystem fault while writing becomes a configuration error."""
        error = OSError("read-only filesystem")

        with pytest.raises(gate.GateConfigError) as raised:
            gate.record_allow_entry(
                ("hecate/a.py", "hecate/b.py"),
                "reviewed",
                gate.AllowDependencies(
                    detector=_double(detector.normalize_findings(STUB_REPORT)),
                    pyproject_path=tmp_path / "pyproject.toml",
                    writer=_double(error),
                ),
            )

        assert str(raised.value) == "read-only filesystem", (
            "The writer's own message must survive translation."
        )
        assert raised.value.__cause__ is error, (
            "The original write fault must stay attached as the cause."
        )

    def test_leaves_a_tool_error_untranslated(self, tmp_path: Path) -> None:
        """A detector provisioning fault keeps its own label and identity."""
        error = detector.GateExecutionError("make install-nose")

        with pytest.raises(gate.GateExecutionError) as raised:
            gate.record_allow_entry(
                ("hecate/a.py",),
                "reviewed",
                gate.AllowDependencies(
                    detector=_double(error),
                    pyproject_path=tmp_path / "pyproject.toml",
                    writer=_double(None),
                ),
            )

        assert raised.value is error, (
            "A tool error must propagate rather than be relabelled."
        )


class TestSeamTranslation:
    """The contracts the gate's two dependency seams must satisfy."""

    def test_read_allowlist_returns_the_reader_result(self) -> None:
        """A successful reader result reaches the caller unchanged."""
        entry = allowlist.AllowEntry(keys=("hecate/a.py",), reason="reviewed")
        assert gate._read_allowlist(_double((entry,))) == (entry,), (
            "The reader's entries must pass through unchanged."
        )

    def test_detect_findings_returns_the_detector_result(self) -> None:
        """A successful detector result reaches the caller unchanged."""
        finding = detector.Finding(
            witness="copy-paste",
            value=9.0,
            locations=(
                detector.Location(file="hecate/a.py", start=1, end=2, name=None),
                detector.Location(file="hecate/b.py", start=1, end=2, name=None),
            ),
        )
        assert gate._detect_findings(_double([finding])) == [finding], (
            "The detector's findings must pass through unchanged."
        )

    @pytest.mark.parametrize(
        ("seam", "error", "expected_type", "expected_message"),
        [
            pytest.param(
                "allowlist",
                OSError("unreadable configuration"),
                gate.GateExecutionError,
                "cannot load duplication allowlist: unreadable configuration",
                id="allowlist-os-error",
            ),
            pytest.param(
                "allowlist",
                tomllib.TOMLDecodeError("bad table", "", 0),
                gate.GateExecutionError,
                "cannot load duplication allowlist: bad table (at end of document)",
                id="allowlist-toml-error",
            ),
            pytest.param(
                "detector",
                OSError("detector executable unavailable"),
                gate.GateExecutionError,
                "nose detector failed: detector executable unavailable",
                id="detector-os-error",
            ),
            pytest.param(
                "detector",
                TypeError("families must be an array"),
                gate.GateConfigError,
                "families must be an array",
                id="detector-type-error",
            ),
            pytest.param(
                "detector",
                ValueError("value must be a number"),
                gate.GateConfigError,
                "value must be a number",
                id="detector-value-error",
            ),
        ],
    )
    def test_seams_translate_dependency_failures(
        self,
        seam: str,
        error: Exception,
        expected_type: type[Exception],
        expected_message: str,
    ) -> None:
        """Each seam maps its dependency's failures onto the gate's own errors.

        Both seams share one contract: the diagnostic names the cause, and the
        original error stays attached as ``__cause__`` so a traceback still
        reaches the real fault. An execution fault and a configuration fault
        land on different gate errors, which is what keeps a rules change
        distinct from a missing binary.
        """
        call = {
            "allowlist": lambda: gate._read_allowlist(_double(error)),
            "detector": lambda: gate._detect_findings(_double(error)),
        }[seam]

        with pytest.raises(expected_type) as raised:
            call()

        assert str(raised.value) == expected_message, "Diagnostic must name the cause."
        assert raised.value.__cause__ is error, "The original error must be the cause."

    def test_detect_findings_does_not_wrap_runtime_errors(self) -> None:
        """Programming faults from a detector are not reclassified as I/O failures."""
        error = RuntimeError("detector runtime failed")

        with pytest.raises(RuntimeError) as raised:
            gate._detect_findings(_double(error))

        assert raised.value is error, "Runtime errors must propagate unchanged."

    def test_read_allowlist_passes_configuration_errors_through(self) -> None:
        """An allowlist configuration error is not rewrapped."""
        error = gate.GateConfigError("duplication_gate.allow[0] requires a reason")

        with pytest.raises(gate.GateConfigError) as raised:
            gate._read_allowlist(_double(error))

        assert raised.value is error, "The original configuration error must propagate."

    def test_detect_findings_passes_configuration_errors_through(self) -> None:
        """A detector configuration error is not rewrapped."""
        error = gate.GateConfigError("nose 0.19.0 is installed but 0.20.0 is pinned")

        with pytest.raises(gate.GateConfigError) as raised:
            gate._detect_findings(_double(error))

        assert raised.value is error, "The original configuration error must propagate."
