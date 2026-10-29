"""Subprocess-level contention tests for the duplication gate.

The gate's allow commands take an advisory lock before they rewrite
``pyproject.toml``, and the tests that prove the lock excludes them have to
start real writers and watch what the kernel does. That machinery -- the copied
workspace, the writers, the kernel probe, the portable lock-attempt recorder,
and the run object that owns the processes -- is substantial and has nothing to
do with reading or appending an allow entry. Keeping it here leaves each test
module with one responsibility.

The module holds the process machinery and the three tests that use it, so
the instrumentation and its only callers stay together. The persistence tests
for reading and writing allow entries live in
``test_duplication_gate_persistence``.
"""

from __future__ import annotations

import dataclasses as dc
import enum
import fcntl
import subprocess  # noqa: S404 - tests start fixed gate commands.
import sys
import time
import tomllib
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    STUB_FAMILY,
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
            **STUB_FAMILY,
            "locations": [location],
        }
        for location in (
            {"file": "hecate/a.py", "start": 1, "end": 20, "name": None},
            {"file": "hecate/b.py", "start": 30, "end": 49, "name": None},
        )
    ],
}

#: How long the blocking probe waits for both writers to reach the lock.
_CONTENTION_TIMEOUT_SECONDS = 30.0

#: How long a process is given to finish once the lock has been released.
_WRITER_GRACE_SECONDS = 60.0


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


def _before_the_lock() -> subprocess.Popen[str]:
    """Start a process that waits, holding nothing.

    It is the negative control for the lock probe: alive for every moment the
    probe samples it, so a probe that reported a lock wait from liveness
    rather than from the kernel would report this process too.
    """
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


class _ProbeOutcome(enum.Enum):
    """What the kernel probe managed to establish about a contention run.

    A plain ``bool`` cannot distinguish "the writers were not seen waiting"
    from "the probe could not read the files it needs", and the second must
    never be reported as the first: it would look like evidence that the lock
    is not contested when nothing was measured at all.
    """

    BLOCKED = "blocked"
    """Every writer was observed in a lock wait."""

    NOT_BLOCKED = "not-blocked"
    """Some writer exited, or the deadline passed, without being observed."""

    UNINSPECTABLE = "uninspectable"
    """The probe could not read the files it needs for at least one writer."""


def _wait_channel_evidence(pid: int) -> str | None:
    """Return the kernel's wait channel and syscall text for ``pid``.

    ``None`` means the kernel would not report them, which is a different
    answer from "not blocked" and is reported as such.
    """
    try:
        channel = Path(f"/proc/{pid}/wchan").read_text(encoding="utf-8").strip()
        syscall = Path(f"/proc/{pid}/syscall").read_text(encoding="utf-8")
    except OSError:
        return None
    return f"{channel} {syscall}"


def _is_blocked_on_the_lock(pid: int) -> bool | None:
    """Report whether ``pid`` is sleeping in a lock wait.

    The kernel names the wait channel and the in-progress syscall for a
    sleeping task, and an ``flock`` wait shows up in both, so a process
    reported here has genuinely reached the contested lock rather than merely
    started. Liveness cannot answer that: a process still importing modules is
    equally alive.

    Returns
    -------
    bool | None
        ``True`` or ``False`` when the kernel answered, and ``None`` when it
        would not report the files this needs.
    """
    evidence = _wait_channel_evidence(pid)
    if evidence is None:
        return None
    return "flock" in evidence or "locks_lock_inode_wait" in evidence


def _probe_is_usable() -> bool:
    """Report whether the kernel probe can read the files it needs.

    The guard must ask the same question the probe asks. Checking only this
    process's ``wchan`` was not enough: on a host that restricts other
    processes' ``syscall`` files, the guard passed while the probe could never
    answer, and the test then waited out the whole deadline and failed instead
    of reporting that inspection was unavailable.

    A live process that is deliberately not waiting is used as the subject, so
    the check exercises exactly the shape the probe will meet: another pid,
    both files, and a definite answer rather than silence.
    """
    probe = _before_the_lock()
    try:
        return _is_blocked_on_the_lock(probe.pid) is not None
    finally:
        probe.kill()
        probe.wait(timeout=_WRITER_GRACE_SECONDS)


def _lock_refuses_a_second_acquirer(pyproject: Path) -> bool:
    """Report whether the held lock refuses another non-blocking acquirer.

    This is the portable half of the contention evidence. It does not depend
    on ``/proc``: it opens the same sidecar the gate locks and attempts the
    same exclusive lock without blocking. While the caller holds the lock the
    attempt must be refused, which demonstrates exclusion by exercising it
    rather than inferring it from a quiet interval.
    """
    lock_path = pyproject.with_name(f".{pyproject.name}.duplication-gate.lock")
    with lock_path.open("a+", encoding="utf-8") as acquirer:
        try:
            fcntl.flock(acquirer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(acquirer.fileno(), fcntl.LOCK_UN)
        return False


#: The sitecustomize planted in each portable writer's working directory.
#:
#: ``allow`` reaches its lock through ``fcntl.flock`` inside
#: ``duplication_allowlist._locked_file``. Importing ``fcntl`` in the writer
#: and wrapping its ``flock`` records the attempt before the call, on every
#: POSIX host, with no ``/proc`` and no dependence on the writer's timing. The
#: record is made *before* the lock is requested, so a line means "this writer
#: is about to contend" and the held lock's refusal is observed for that same
#: attempt through ``_lock_refuses_a_second_acquirer``.
#:
#: The wrapper is installed by ``sitecustomize`` because the copied gate is a
#: separate interpreter: there is no in-process seam to monkeypatch. Only the
#: ``LOCK_EX`` path is recorded, so the ``LOCK_UN`` release is untouched.
_LOCK_ATTEMPT_HOOK = """\
import fcntl as _fcntl
import os as _os

_attempt_log = _os.environ.get("DUP_GATE_ATTEMPT_LOG")
_original_flock = _fcntl.flock


def _recording_flock(fd, operation):
    if (
        _attempt_log
        and operation & _fcntl.LOCK_EX
        and not operation & _fcntl.LOCK_NB
    ):
        with open(_attempt_log, "a", encoding="utf-8") as log:
            log.write(f"{_os.getpid()}\\n")
    return _original_flock(fd, operation)


_fcntl.flock = _recording_flock
"""


def _await_lock_attempt(
    writers: tuple[subprocess.Popen[str], ...],
    attempt_log: Path,
    *,
    deadline_seconds: float = _CONTENTION_TIMEOUT_SECONDS,
) -> set[int]:
    """Block until every writer has entered the blocking lock call.

    Each portable writer imports a ``sitecustomize`` that records its pid just
    before it makes the blocking exclusive ``flock`` call. That is positive
    evidence the writer reached the contested operation, not an inference from
    elapsed time: a writer still importing modules has recorded nothing. The
    wait is bounded, and a writer that exits first fails loudly with its own
    output rather than being waited out.

    Returns
    -------
    set[int]
        The writer pids whose lock attempt was recorded.
    """
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        for writer in writers:
            if writer.poll() is not None:
                stdout, stderr = writer.communicate()
                pytest.fail(
                    f"a writer exited before attempting the lock: "
                    f"returncode={writer.returncode} stdout={stdout!r} "
                    f"stderr={stderr!r}",
                    pytrace=False,
                )
        attempted = _recorded_attempts(attempt_log)
        if len(attempted) >= len(writers):
            return attempted
        time.sleep(0.05)
    attempted = _recorded_attempts(attempt_log)
    pytest.fail(
        f"{len(attempted)} of {len(writers)} writers attempted the lock "
        f"within {deadline_seconds}s: {sorted(attempted)!r}",
        pytrace=False,
    )


def _recorded_attempts(attempt_log: Path) -> set[int]:
    """Return the pids whose lock attempt the instrumented writers recorded."""
    return {int(line) for line in attempt_log.read_text(encoding="utf-8").splitlines()}


def _await_blocked(
    writers: tuple[subprocess.Popen[str], ...],
    *,
    blocked_at: dict[str, float],
    deadline_seconds: float = _CONTENTION_TIMEOUT_SECONDS,
) -> _ProbeOutcome:
    """Wait until every writer is in a lock wait, or the deadline passes.

    Each writer's wait is recorded in ``blocked_at`` as it is observed, so the
    caller can show the writers overlapped on the lock rather than reaching it
    one after the other.

    Returns
    -------
    _ProbeOutcome
        ``BLOCKED`` once every writer has been observed in a lock wait,
        ``UNINSPECTABLE`` as soon as the kernel declines to report one, and
        ``NOT_BLOCKED`` when a writer exits or the deadline passes first.
    """
    deadline = time.monotonic() + deadline_seconds
    pending = list(writers)
    while pending and time.monotonic() < deadline:
        for writer in list(pending):
            if writer.poll() is not None:
                return _ProbeOutcome.NOT_BLOCKED
            blocked = _is_blocked_on_the_lock(writer.pid)
            if blocked is None:
                # The kernel will not answer for this writer. Waiting out the
                # deadline here would report a slow test rather than the real
                # problem, so give up at the first unanswered probe.
                return _ProbeOutcome.UNINSPECTABLE
            if blocked:
                blocked_at[str(writer.pid)] = time.monotonic()
                pending.remove(writer)
        if pending:
            time.sleep(0.05)
    return _ProbeOutcome.BLOCKED if not pending else _ProbeOutcome.NOT_BLOCKED


@dc.dataclass(frozen=True, slots=True)
class _ContendedSetup:
    """The copied workspace and control process a contention run starts from.

    Building this is separated from observing the lock so the observation
    itself has one job: take the lock, start the writers, and report what the
    probe saw.
    """

    script: Path
    environment: dict[str, str]
    pyproject: Path
    bystander: subprocess.Popen[str]
    attempt_log: Path


def _contended_setup(tmp_path: Path) -> _ContendedSetup:
    """Copy the gate into ``tmp_path`` and start the negative-control process.

    The writers run as separate interpreters with no in-process seam to
    monkeypatch, so the ``sitecustomize`` hook is placed beside the copied
    gate and reached through ``PYTHONPATH``. It records each writer's pid when
    it enters the blocking exclusive-lock call, which is the portable
    contention signal the kernel probe cannot provide off Linux.
    """
    workspace, script = copied_gate_workspace(tmp_path)
    (script.parent / "sitecustomize.py").write_text(
        _LOCK_ATTEMPT_HOOK, encoding="utf-8"
    )
    attempt_log = tmp_path / "lock-attempts.txt"
    attempt_log.touch()
    stub = write_stub_nose(tmp_path, report=_TWO_FAMILY_REPORT)
    return _ContendedSetup(
        script=script,
        environment=gate_environment(
            NOSE_BIN=str(stub),
            PYTHONPATH=str(script.parent),
            DUP_GATE_ATTEMPT_LOG=str(attempt_log),
        ),
        pyproject=workspace / "pyproject.toml",
        bystander=_before_the_lock(),
        attempt_log=attempt_log,
    )


def _terminate(
    writers: list[subprocess.Popen[str]], bystander: subprocess.Popen[str]
) -> None:
    """Kill every process a failed contention run started.

    The control sleeps far longer than any grace period here on purpose, so it
    is always killed rather than waited for.
    """
    for writer in writers:
        writer.kill()
        writer.wait(timeout=_WRITER_GRACE_SECONDS)
    bystander.kill()
    bystander.wait(timeout=_WRITER_GRACE_SECONDS)


class _ObservationMode(enum.Enum):
    """Which evidence a held-lock observation collects.

    The two modes answer different questions and need different machinery.
    ``KERNEL_PROBE`` establishes that the writers genuinely reached the lock
    by reading the kernel's wait channel, which is strong evidence but Linux
    only. ``PORTABLE_EXCLUSION`` establishes that the held lock refuses
    another acquirer and that no writer replaced the manifest, which works
    anywhere but is a bounded exclusion check rather than a proof that the
    writers were blocked. Keeping them separate stops the portable case from
    paying the kernel probe's deadline on a host that cannot answer it, and
    stops either case from claiming the other's guarantee.
    """

    KERNEL_PROBE = "kernel-probe"
    PORTABLE_EXCLUSION = "portable-exclusion"


@dc.dataclass(frozen=True, slots=True)
class _LockObservation:
    """What the probe saw while the test held the lock.

    These facts are always read together -- they answer one question, "did the
    lock actually exclude the writers?" -- so they travel as one value rather
    than as fields the caller has to keep straight.

    Attributes
    ----------
    blocked_at : dict[str, float]
        Monotonic times at which each writer was seen waiting on the lock,
        keyed by process id as text. Empty in portable mode, which does not
        inspect the kernel.
    bystander_blocked : bool | None
        Whether the probe ever reported the control as waiting. It must not,
        and a ``True`` here means the probe is measuring something other than
        contention. ``None`` in portable mode, where no kernel probe runs.
    original_manifest : bytes
        The manifest before either writer started.
    held_manifest : bytes
        The manifest as it read while the lock was still held. The lock's
        whole purpose is that no writer replaces the file during that window,
        so this differing from the original is a lock that did not hold.
    probe_outcome : _ProbeOutcome | None
        How far the kernel probe got, so a caller can tell "not blocked" from
        "could not inspect". ``None`` in portable mode, where no probe runs.
    lock_refused_second_acquirer : bool
        Whether the held lock refused a second, non-blocking acquirer. This is
        the portable evidence, independent of ``/proc``.
    attempted_lock_pids : set[int]
        The writer pids whose entry into the blocking exclusive-lock call was
        recorded by the writer's own instrumentation. Empty in kernel-probe
        mode, which does not instrument the writers.
    """

    blocked_at: dict[str, float]
    bystander_blocked: bool | None
    original_manifest: bytes
    held_manifest: bytes
    probe_outcome: _ProbeOutcome | None
    lock_refused_second_acquirer: bool
    attempted_lock_pids: set[int]


def _observe_lock(
    writers: list[subprocess.Popen[str]],
    setup: _ContendedSetup,
    *,
    mode: _ObservationMode,
) -> _LockObservation:
    """Observe what the held lock does before releasing it.

    The caller holds the lock when this is called. In ``KERNEL_PROBE`` mode
    the kernel wait channel is read until both writers are seen waiting, and
    the bystander is sampled as the liveness control. In
    ``PORTABLE_EXCLUSION`` mode the test instead waits for each writer's own
    readiness line and makes a non-blocking acquisition attempt; that attempt
    works on every platform and is what the portable case's exclusion claim
    rests on.

    A writer that ignored the lock is caught by the manifest check, which is
    read before the writers start and again just before the lock is released.
    In portable mode the wait between those reads is the readiness signal, not
    a sleep: the test knows each writer has finished its startup, so the check
    covers the window in which a bypassing writer could replace the file.
    """
    blocked_at: dict[str, float] = {}
    original_manifest = setup.pyproject.read_bytes()
    probe_outcome: _ProbeOutcome | None = None
    bystander_blocked: bool | None = None
    attempted_lock_pids: set[int] = set()
    if mode is _ObservationMode.KERNEL_PROBE:
        probe_outcome = _await_blocked(tuple(writers), blocked_at=blocked_at)
        bystander_blocked = _is_blocked_on_the_lock(setup.bystander.pid) is True
    else:
        attempted_lock_pids = _await_lock_attempt(tuple(writers), setup.attempt_log)
    lock_refused = _lock_refuses_a_second_acquirer(setup.pyproject)
    held_manifest = setup.pyproject.read_bytes()
    return _LockObservation(
        blocked_at=blocked_at,
        bystander_blocked=bystander_blocked,
        original_manifest=original_manifest,
        held_manifest=held_manifest,
        probe_outcome=probe_outcome,
        lock_refused_second_acquirer=lock_refused,
        attempted_lock_pids=attempted_lock_pids,
    )


@dc.dataclass(frozen=True, slots=True)
class _ContendedRun:
    """Two ``allow`` commands started while the test held the lock.

    Attributes
    ----------
    writers : tuple[subprocess.Popen[str], ...]
        The two ``allow`` processes, both started before the lock was
        released.
    bystander : subprocess.Popen[str]
        The control process, alive throughout and holding nothing.
    pyproject : pathlib.Path
        The manifest both writers were asked to update.
    observation : _LockObservation
        What the probe saw while the lock was held.
    """

    writers: tuple[subprocess.Popen[str], ...]
    bystander: subprocess.Popen[str]
    pyproject: Path
    observation: _LockObservation

    @property
    def blocked_at(self) -> dict[str, float]:
        """Return the monotonic times each writer was seen waiting."""
        return self.observation.blocked_at

    @property
    def bystander_blocked(self) -> bool | None:
        """Return whether the probe ever reported the control as waiting."""
        return self.observation.bystander_blocked

    @property
    def original_manifest(self) -> bytes:
        """Return the manifest as it read before either writer started."""
        return self.observation.original_manifest

    @property
    def held_manifest(self) -> bytes:
        """Return the manifest as it read while the lock was still held."""
        return self.observation.held_manifest

    @property
    def probe_outcome(self) -> _ProbeOutcome | None:
        """Return how far the kernel probe got, or ``None`` if none ran."""
        return self.observation.probe_outcome

    @property
    def lock_refused_second_acquirer(self) -> bool:
        """Return whether the held lock refused a second acquirer."""
        return self.observation.lock_refused_second_acquirer

    @property
    def attempted_lock_pids(self) -> set[int]:
        """Return the writer pids recorded entering the blocking lock call."""
        return self.observation.attempted_lock_pids

    def reap(self, *, grace_seconds: float = _WRITER_GRACE_SECONDS) -> None:
        """Wait for every process this run started, killing any straggler.

        A writer still waiting on the lock holds its stdout and stderr pipes
        open, so a failing assertion above would otherwise leak processes and
        descriptors into the rest of the run.

        The control is killed rather than waited for: it sleeps far longer
        than any grace period here on purpose, precisely so that it is still
        alive after the observation, so waiting on it could only ever burn the
        whole grace period.
        """
        self.bystander.kill()
        self.bystander.wait(timeout=grace_seconds)
        for writer in self.writers:
            try:
                writer.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                writer.kill()
                writer.wait(timeout=grace_seconds)

    def recorded_units(self) -> set[str]:
        """Return the unit keys the writers recorded in the manifest.

        Each ``allow`` command is a read-modify-write of the same file, so an
        entry missing here is one a concurrent writer overwrote rather than
        appended beside.
        """
        document = tomllib.loads(self.pyproject.read_text(encoding="utf-8"))
        entries = document["tool"]["duplication_gate"]["allow"]
        return {entry["unit"] for entry in entries}

    @classmethod
    def start_and_release(
        cls, tmp_path: Path, *, mode: _ObservationMode
    ) -> _ContendedRun:
        """Start both writers against a held lock, then release it.

        The lock is taken through the module's own ``_locked_file`` rather
        than with a hand-rolled ``flock``, so the writers queue against the
        same helper the gate uses. Both are started before the lock is
        released, which is what makes the run concurrent whoever wins.

        Parameters
        ----------
        tmp_path : pathlib.Path
            Directory to build the copied workspace inside.
        mode : _ObservationMode
            Which evidence to collect while the lock is held. ``KERNEL_PROBE``
            waits for the kernel to show each writer in a lock wait;
            ``PORTABLE_EXCLUSION`` waits for each writer's readiness line and
            makes a non-blocking acquisition attempt instead.
        """
        setup = _contended_setup(tmp_path)
        writers: list[subprocess.Popen[str]] = []
        try:
            with allowlist._locked_file(setup.pyproject):
                writers.extend(
                    _start_writer(setup.script, key, reason, setup.environment)
                    for key, reason in (
                        ("hecate/a.py", "first writer"),
                        ("hecate/b.py", "second writer"),
                    )
                )
                observation = _observe_lock(writers, setup, mode=mode)
        except BaseException:
            _terminate(writers, setup.bystander)
            raise
        return cls(
            writers=tuple(writers),
            bystander=setup.bystander,
            pyproject=setup.pyproject,
            observation=observation,
        )


class TestAllowCommandsContendForTheLock:
    """Subprocess-level evidence that the allow commands exclude each other.

    These tests start real ``allow`` processes and observe the advisory lock
    the writer takes. They live apart from the persistence tests because they
    assert a different property -- exclusion between concurrent processes --
    and because they share the process machinery above rather than the
    ``append_allow_entry`` surface those tests exercise.
    """

    def test_concurrent_allow_commands_preserve_both_entries(
        self, tmp_path: Path
    ) -> None:
        """Two blocked writers retain both exceptions after the lock releases.

        Contention here is a kernel observation, not an inference from two
        live processes: each writer is seen inside an ``flock`` wait while the
        test holds the lock, and the timestamps show they waited at the same
        time rather than one after the other. The bystander is the control for
        that claim -- it stays alive throughout and must never be seen in a
        lock wait -- and the test skips on a host whose kernel does not expose
        the wait channel, because without it the assertion could pass with the
        lock removed and would prove nothing.
        """
        if not _probe_is_usable():
            pytest.skip(
                "this host does not let the probe read another process's "
                "kernel wait channel, so contention cannot be observed here; "
                "the entry-preservation assertion would hold even for two "
                "serial writers."
            )
        run = _ContendedRun.start_and_release(
            tmp_path, mode=_ObservationMode.KERNEL_PROBE
        )
        try:
            if run.probe_outcome is _ProbeOutcome.UNINSPECTABLE:
                pytest.skip(
                    "the kernel stopped reporting a writer's wait channel "
                    "mid-run, so this run cannot be read as contention "
                    "evidence; the next run may inspect it."
                )
            assert run.probe_outcome is _ProbeOutcome.BLOCKED, (
                "Both writers must be observed waiting on the lock the test "
                "held, or this is not a contention test."
            )
            assert len(run.blocked_at) == 2, (
                "Both writers must be observed waiting on the lock the test "
                "held, or this is not a contention test."
            )
            assert not run.bystander_blocked, (
                "A process holding nothing was reported as waiting on the "
                "lock, so the probe is not measuring contention."
            )
            assert run.bystander.poll() is None, (
                "The control process must outlive the observation, or it "
                "cannot distinguish liveness from a lock wait."
            )
            for writer in run.writers:
                assert writer.wait(timeout=_WRITER_GRACE_SECONDS) == 0, (
                    "Each writer must complete successfully once the lock is free."
                )
        finally:
            run.reap()

        assert len({writer.pid for writer in run.writers}) == 2, (
            "The writers must be distinct processes."
        )
        assert run.recorded_units() == {"hecate/a.py", "hecate/b.py"}, (
            "Concurrent commands must preserve both independently added entries."
        )

    def test_a_held_lock_excludes_the_writers_whatever_the_platform(
        self, tmp_path: Path
    ) -> None:
        """The held lock refuses another acquirer and no writer replaces it.

        This is the portable half of the contention evidence, and it does not
        depend on ``/proc``. Three facts are asserted separately because they
        answer different questions:

        * each writer entered the blocking exclusive-lock call while the test
          held the lock, recorded by the writer's own instrumentation. Without
          this, the other two assertions would also hold for two writers that
          had not started yet;
        * the held lock refuses a second, non-blocking acquirer, which
          demonstrates exclusion by exercising it rather than inferring it
          from a quiet interval;
        * no writer replaced the manifest during the held window, which is the
          effect the lock exists to produce.

        It is a bounded exclusion check, not the equivalent of the kernel
        probe's proof of contention: entering the call shows a writer
        contended, and the refusal shows the lock excluded it, but neither
        reads the writer's blocked state directly.
        """
        run = _ContendedRun.start_and_release(
            tmp_path, mode=_ObservationMode.PORTABLE_EXCLUSION
        )
        try:
            assert run.attempted_lock_pids == {writer.pid for writer in run.writers}, (
                "Both writers must have entered the blocking lock call while "
                "the lock was held. A writer that never got there makes the "
                "exclusion assertion below trivially true."
            )
            assert run.lock_refused_second_acquirer, (
                "The held lock admitted a second acquirer, so it is not "
                "excluding anything and the observation below proves nothing."
            )
            assert run.probe_outcome is None, (
                "The portable case must not pay the kernel probe's deadline; "
                "it collects exclusion evidence instead."
            )
            assert b"duplication_gate" not in run.held_manifest, (
                "An entry appeared during the held window, which means a "
                "writer recorded it without acquiring the lock."
            )
            assert run.held_manifest == run.original_manifest, (
                "The manifest changed while the lock was held, so a writer "
                "replaced it without waiting: `held_manifest` should still "
                "read as the configuration the run started from."
            )
        finally:
            run.reap()

        assert run.recorded_units() == {"hecate/a.py", "hecate/b.py"}, (
            "Both writers must still record their entries once released."
        )

    def test_liveness_alone_does_not_prove_contention(self, tmp_path: Path) -> None:
        """The negative control: the probe answers the lock, not the process.

        A writer that never reaches the lock -- still importing, or simply
        doing something else -- is as alive as one that has, so a probe built
        on liveness would report both. This starts the control process first
        and samples it for far longer than a real writer needs to reach the
        lock, then asserts it was never reported. It is the test above's other
        half: that one shows a real wait is found, this one shows merely being
        alive is not counted as one.
        """
        if not _probe_is_usable():
            pytest.skip(
                "this host does not let the probe read another process's "
                "kernel wait channel, so there is no probe here whose silence "
                "could mean anything."
            )
        bystander = _before_the_lock()
        blocked_at: dict[str, float] = {}
        try:
            outcome = _await_blocked(
                (bystander,), blocked_at=blocked_at, deadline_seconds=2.0
            )
            assert outcome is _ProbeOutcome.NOT_BLOCKED, (
                "A process that never enters a lock wait must be reported as "
                f"not blocked, got {outcome}."
            )
            assert blocked_at == {}, "No wait was entered, so none must be recorded."
        finally:
            # The control sleeps far longer than the observation on purpose,
            # so it is stopped rather than waited out.
            bystander.kill()
            bystander.wait(timeout=_WRITER_GRACE_SECONDS)
