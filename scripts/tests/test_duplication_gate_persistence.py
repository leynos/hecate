"""Persistence and contention tests for duplication-gate allow entries."""

from __future__ import annotations

import subprocess  # noqa: S404 - tests exercise copied gate commands.
import time
import tomllib
from pathlib import Path

import pytest
import tomlkit.exceptions
from duplication_gate_test_support import (
    STUB_REPORT,
    allowlist,
    copied_gate_workspace,
    gate_command,
    gate_environment,
    write_stub_nose,
)

#: A report with one deployable family per writer key, so each writer's
#: `allow` run covers a real family and is not refused by the coverage check.
_TWO_FAMILY_REPORT: dict[str, object] = {
    **STUB_REPORT,
    "families": [
        {
            **STUB_REPORT["families"][0],
            "locations": [location],
        }
        for location in (
            {"file": "hecate/a.py", "start": 1, "end": 20, "name": None},
            {"file": "hecate/b.py", "start": 30, "end": 49, "name": None},
        )
    ],
}

#: Kernel wait channel reported by Linux while a process sleeps inside
#: `fcntl.flock`. Matched as a substring so a neighbouring kernel revision
#: naming the same wait differently still counts as evidence of blocking.
_FLOCK_WAIT_CHANNELS = ("locks_lock_inode_wait", "flock")

#: How long the contention probe waits for both writers to reach the lock.
_CONTENTION_TIMEOUT_SECONDS = 30.0


def _start_writer(
    script: Path, key: str, reason: str, environment: dict[str, str]
) -> subprocess.Popen[str]:
    """Start one allow command in the background and return its handle."""
    return subprocess.Popen(  # noqa: S603 - fixed copied gate command.
        gate_command(script, "allow", "--first", key, "--reason", reason),
        cwd=script.parent.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _is_blocked_on_a_lock(pid: int) -> bool:
    """Report whether ``pid`` is currently sleeping in a lock wait.

    The kernel exposes the wait channel and the in-progress syscall for a
    sleeping task, and ``flock`` shows up as both. A reader that cannot see
    ``/proc`` -- a platform without it, or a hardened kernel -- reports
    ``False``, and the caller falls back to the timestamp check rather than
    treating the absence of evidence as evidence of contention.
    """
    try:
        channel = Path(f"/proc/{pid}/wchan").read_text(encoding="utf-8").strip()
        syscall = Path(f"/proc/{pid}/syscall").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in channel for marker in _FLOCK_WAIT_CHANNELS) or (
        "flock" in syscall
    )


def _await_blocked_on_lock(
    writers: list[subprocess.Popen[str]],
    *,
    blocked_at: dict[str, float],
    deadline_seconds: float = _CONTENTION_TIMEOUT_SECONDS,
) -> bool:
    """Wait until every writer is provably blocked on the held lock.

    Records each writer's blocking timestamp in ``blocked_at`` as it is
    observed, so the caller can show that the writers overlapped on the lock
    rather than passing through it one at a time.

    Returns
    -------
    bool
        ``True`` once every writer has been observed waiting on the lock.
    """
    deadline = time.monotonic() + deadline_seconds
    pending = list(writers)
    while pending and time.monotonic() < deadline:
        for writer in list(pending):
            if writer.poll() is not None:
                return False
            if _is_blocked_on_a_lock(writer.pid):
                blocked_at[str(writer.pid)] = time.monotonic()
                pending.remove(writer)
        if pending:
            time.sleep(0.05)
    return not pending


class TestLoadAllowEntry:
    """Reading reasoned entries without touching the file."""

    def test_loader_never_reaches_the_writer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reading the allowlist must not open, lock, or replace the file."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[[tool.duplication_gate.allow]]\n"
            'unit = "hecate/a.py"\n'
            'reason = "reviewed"\n',
            encoding="utf-8",
        )
        before = pyproject.stat()

        def refuse(*_args: object, **_kwargs: object) -> None:
            msg = "the read-only loader must not write"
            raise AssertionError(msg)

        monkeypatch.setattr(allowlist, "atomic_write", refuse)
        monkeypatch.setattr(allowlist, "_locked_file", refuse)

        entries = allowlist.load_allowlist(pyproject)

        assert [entry.keys for entry in entries] == [("hecate/a.py",)], (
            "The loader must return the parsed entries."
        )
        after = pyproject.stat()
        assert (after.st_mtime_ns, after.st_size) == (
            before.st_mtime_ns,
            before.st_size,
        ), "Loading must leave the file untouched."
        assert list(tmp_path.glob(".pyproject.toml.*")) == [], (
            "Loading must not leave a lock or temporary sibling behind."
        )

    def test_loader_creates_no_file_when_the_document_is_absent(
        self, tmp_path: Path
    ) -> None:
        """An absent allowlist loads as empty rather than being created."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\n', encoding="utf-8")

        assert allowlist.load_allowlist(pyproject) == (), (
            "A document without an allow table must load no entries."
        )
        assert list(tmp_path.iterdir()) == [pyproject], (
            "Loading must not create sibling files."
        )


class TestAppendAllowEntry:
    """Persisting reasoned entries to ``pyproject.toml``."""

    def test_round_trips_unit_and_pair_entries(self, tmp_path: Path) -> None:
        """Appended entries load again and preserve existing TOML content."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")
        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/a.py",),
            reason="unit reason",
        )
        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/b.py::beta", "hecate/c.py::gamma"),
            reason="members reason",
        )
        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/c.py::gamma", "hecate/b.py::beta"),
            reason="updated members reason",
        )

        entries = allowlist.load_allowlist(pyproject)
        assert entries[0].keys == ("hecate/a.py",), "Unit entry must retain its target."
        assert entries[1].keys == ("hecate/b.py::beta", "hecate/c.py::gamma"), (
            "Members entry must retain both targets."
        )
        assert entries[1].reason == "updated members reason", (
            "A repeated member set must update its reason."
        )
        assert len(entries) == 2, "A repeated member set must not add an entry."
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert data["project"]["name"] == "x", (
            "Appending must preserve existing TOML content."
        )

    def test_preserves_comments_and_unrelated_configuration(
        self, tmp_path: Path
    ) -> None:
        """Recording an exception leaves surrounding prose and tables intact."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "x"\nversion = "0"\n'
            "\n"
            "# Keep this table documented in prose.\n"
            "[tool.nose]\n"
            'version = "0.20.0"\n'
            "roots = [\"hecate\"]\n",
            encoding="utf-8",
        )

        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/a.py",),
            reason="reviewed exception",
        )

        written = pyproject.read_text(encoding="utf-8")
        assert "# Keep this table documented in prose." in written, (
            "Existing TOML comments must survive a recorded exception."
        )
        assert 'roots = ["hecate"]' in written, (
            "Unrelated configuration must survive a recorded exception."
        )

    def test_reordering_members_updates_in_place(self, tmp_path: Path) -> None:
        """A reordered member set is the same target and is not duplicated."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[[tool.duplication_gate.allow]]\n"
            'members = ["hecate/a.py", "hecate/b.py"]\n'
            'reason = "first reason"\n',
            encoding="utf-8",
        )

        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/b.py", "hecate/a.py"),
            reason="reordered reason",
        )

        entries = allowlist.load_allowlist(pyproject)
        assert len(entries) == 1, "Reordered members must not add a second entry."
        assert entries[0].reason == "reordered reason", (
            "Reordered members must update the existing entry."
        )

    def test_unparseable_document_raises_a_configuration_error(
        self, tmp_path: Path
    ) -> None:
        """An unparseable manifest is a configuration error, not a traceback."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not = = valid toml\n", encoding="utf-8")

        with pytest.raises(allowlist.GateConfigError) as raised:
            allowlist.append_allow_entry(
                pyproject,
                keys=("hecate/a.py",),
                reason="unit reason",
            )

        assert isinstance(raised.value.__cause__, tomlkit.exceptions.ParseError), (
            "The parse failure must be preserved as the cause."
        )
        assert pyproject.read_text(encoding="utf-8") == (
            "this is not = = valid toml\n"
        ), "A rejected document must be left untouched."

    def test_atomic_write_preserves_mode_and_original_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed replacement retains contents, mode, and a usable lock."""
        pyproject = tmp_path / "pyproject.toml"
        original = '[project]\nname = "x"\nversion = "0"\n'
        pyproject.write_text(original, encoding="utf-8")
        pyproject.chmod(0o640)
        original_replace = Path.replace

        def fail_replace(_source: Path, _destination: Path) -> None:
            msg = "replacement failed"
            raise OSError(msg)

        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(OSError, match="replacement failed"):
            allowlist.append_allow_entry(
                pyproject,
                keys=("hecate/a.py",),
                reason="unit reason",
            )
        monkeypatch.setattr(Path, "replace", original_replace)

        assert pyproject.read_text(encoding="utf-8") == original, (
            "Failed replacement must preserve the original TOML."
        )
        temporary_siblings = [
            path
            for path in tmp_path.glob(".pyproject.toml.*")
            if path.name != ".pyproject.toml.duplication-gate.lock"
        ]
        assert temporary_siblings == [], (
            "Failed replacement must remove its temporary sibling."
        )
        allowlist.append_allow_entry(
            pyproject,
            keys=("hecate/a.py",),
            reason="unit reason",
        )
        assert pyproject.stat().st_mode & 0o777 == 0o640, (
            "Replacement must preserve the destination mode."
        )

    def test_concurrent_allow_commands_preserve_both_entries(
        self, tmp_path: Path
    ) -> None:
        """Two blocked writers retain both exceptions after the lock releases.

        Liveness alone would not evidence contention: a process that has only
        reached an ``import`` is also alive and not yet finished. The test
        therefore waits until the children have started, then proves the
        contested lock is actually held by watching it from outside, and only
        then releases it. Without that step the assertion below would hold
        even if both writers ran serially.
        """
        _workspace, script = copied_gate_workspace(tmp_path)
        stub = write_stub_nose(tmp_path, report=_TWO_FAMILY_REPORT)
        environment = gate_environment(NOSE_BIN=str(stub))
        pyproject = script.parent.parent / "pyproject.toml"
        blocked_at: dict[str, float] = {}

        with allowlist._locked_file(pyproject):
            writers = [
                _start_writer(script, key, reason, environment)
                for key, reason in (
                    ("hecate/a.py", "first writer"),
                    ("hecate/b.py", "second writer"),
                )
            ]
            assert [writer.poll() for writer in writers] == [None, None], (
                "Both writers must be running while the lock is held."
            )
            # A live process may still be importing; only a kernel wait on the
            # lock file proves it reached the contested operation. Recording
            # the moment of that proof is what lets the overlap assertion below
            # be about contention rather than about two processes merely
            # existing at the same time.
            assert _await_blocked_on_lock(writers, blocked_at=blocked_at), (
                "Both writers must block on the lock the test is holding."
            )

        first, second = writers
        try:
            assert first.wait(timeout=20) == 0, "First writer must exit successfully."
            assert second.wait(timeout=20) == 0, "Second writer must exit successfully."
        finally:
            # A timed-out writer blocks on the lock holding its stdout and
            # stderr pipes open. Reap both on the way out so a failure here
            # cannot leak processes or descriptors into the rest of the run.
            for writer in writers:
                if writer.poll() is None:
                    writer.kill()
                writer.wait(timeout=10)

        assert len(blocked_at) == 2, "Both writers must have been shown to block."
        assert first.pid != second.pid, "The writers must be distinct processes."
        entries = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"][
            "duplication_gate"
        ]["allow"]
        recorded_units = {entry["unit"] for entry in entries}
        assert recorded_units == {"hecate/a.py", "hecate/b.py"}, (
            "Concurrent commands must preserve both independently added entries."
        )
