"""Behavioural tests for the atomic replacement helper.

``scripts/atomic_write.py`` is the persistence primitive the duplication
allowlist writer depends on, so these tests pin its public contract directly
rather than through that caller: default parent creation, mode preservation
only when a destination exists, and the descriptor discipline around fsync.
"""

from __future__ import annotations

import dataclasses as dc
import errno
import inspect
import os
import stat
import typing as typ

import pytest
from duplication_gate_test_support import atomic_write

if typ.TYPE_CHECKING:
    from pathlib import Path


def test_writes_new_content(tmp_path: Path) -> None:
    """A new file receives the requested bytes."""
    destination = tmp_path / "pyproject.toml"

    atomic_write.atomic_write(destination, b"[tool.nose]\n")

    assert destination.read_bytes() == b"[tool.nose]\n", (
        "The destination must hold the written content."
    )


def test_replaces_existing_content(tmp_path: Path) -> None:
    """An existing file is replaced rather than appended to."""
    destination = tmp_path / "pyproject.toml"
    destination.write_bytes(b"stale\n")

    atomic_write.atomic_write(destination, b"fresh\n")

    assert destination.read_bytes() == b"fresh\n", (
        "Replacement must discard the previous content."
    )


def test_leaves_no_temporary_sibling(tmp_path: Path) -> None:
    """The temporary file is removed once the write completes."""
    destination = tmp_path / "pyproject.toml"

    atomic_write.atomic_write(destination, b"content\n")

    assert [entry.name for entry in tmp_path.iterdir()] == ["pyproject.toml"], (
        "A completed write must not leave a temporary file behind."
    )


def test_creates_parent_directories_by_default(tmp_path: Path) -> None:
    """The default options create missing destination directories."""
    destination = tmp_path / "missing" / "nested" / "config.toml"

    atomic_write.atomic_write(destination, b"payload\n")

    assert destination.read_bytes() == b"payload\n", (
        "The destination must hold the replacement content."
    )


def test_without_parent_creation_requires_the_directory(tmp_path: Path) -> None:
    """Disabling parent creation surfaces a missing destination directory."""
    destination = tmp_path / "missing" / "config.toml"

    with pytest.raises(FileNotFoundError):
        atomic_write.atomic_write(
            destination,
            b"payload\n",
            options=atomic_write.AtomicWriteOptions(create_parents=False),
        )
    assert not destination.exists(), "A failed write must not create the destination."


def test_preserves_an_existing_destination_mode(tmp_path: Path) -> None:
    """Mode preservation copies the destination's permissions onto the replacement."""
    destination = tmp_path / "config.toml"
    destination.write_bytes(b"old\n")
    destination.chmod(0o640)

    atomic_write.atomic_write(
        destination,
        b"new\n",
        options=atomic_write.AtomicWriteOptions(preserve_mode=True),
    )

    assert destination.read_bytes() == b"new\n", "The content must be replaced."
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640, (
        "Mode preservation must retain the destination's permission bits."
    )


def test_preserves_mode_only_when_a_destination_exists(tmp_path: Path) -> None:
    """Mode preservation must not require an initial destination."""
    destination = tmp_path / "new" / "config.toml"

    atomic_write.atomic_write(
        destination,
        b"new\n",
        options=atomic_write.AtomicWriteOptions(preserve_mode=True),
    )

    assert destination.read_bytes() == b"new\n", (
        "A missing destination must still be created when preserving modes."
    )


def test_default_options_are_shared_rather_than_rebuilt() -> None:
    """The signature default is the module singleton, not a per-call construction."""
    default = inspect.signature(atomic_write.atomic_write).parameters["options"].default
    assert default is atomic_write._DEFAULT_OPTIONS, (
        "The default options must come from the module-level singleton."
    )


@dc.dataclass
class _OsSpy:
    """Record what ``atomic_write`` fsyncs, delegating the rest to ``os``.

    ``atomic_write`` closes every descriptor it syncs before it returns, so
    each descriptor is inspected while it is still open and the ``stat`` result
    kept; a later ``os.fstat`` on the recorded number would raise ``EBADF``.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    synced: list[os.stat_result] = dc.field(default_factory=list)

    def fsync(self, descriptor: int) -> None:
        """Record the descriptor's stat, then sync it for real."""
        self.synced.append(os.fstat(descriptor))
        os.fsync(descriptor)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening."""
        return os.open(path, flags)

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing."""
        os.close(descriptor)


@dc.dataclass
class _FailingDirectorySync:
    """Fail the directory sync, recording which descriptors get closed.

    The first ``fsync`` reaches the temporary file and is allowed through; the
    second reaches the directory and raises. ``atomic_write`` opens the
    directory through ``os.open``, so every descriptor recorded here is the
    directory descriptor, and the ``close`` calls show whether that descriptor
    was released on the failing path.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    syncs: int = 0
    opened: list[int] = dc.field(default_factory=list)
    closed: list[int] = dc.field(default_factory=list)

    def fsync(self, descriptor: int) -> None:
        """Sync the temporary file, then fail on the directory."""
        self.syncs += 1
        if self.syncs > 1:
            message = "directory sync failed"
            raise OSError(message)
        os.fsync(descriptor)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening, recording the descriptor."""
        descriptor = os.open(path, flags)
        self.opened.append(descriptor)
        return descriptor

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing, recording the descriptor."""
        self.closed.append(descriptor)
        os.close(descriptor)


def test_closes_the_directory_descriptor_when_the_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing directory sync must still release the descriptor it opened."""
    destination = tmp_path / "config.toml"
    spy = _FailingDirectorySync()
    monkeypatch.setattr(atomic_write, "os", spy)

    with pytest.raises(OSError, match="directory sync failed"):
        atomic_write.atomic_write(
            destination,
            b"payload\n",
            options=atomic_write.AtomicWriteOptions(sync_file=True),
        )

    assert len(spy.opened) == 1, "The directory descriptor must be opened once."
    assert spy.closed == spy.opened, (
        "The directory descriptor must be closed even when os.fsync raises."
    )
    assert list(tmp_path.glob(f".{destination.name}.*")) == [], (
        "A failed sync must not leave the temporary sibling behind."
    )


@dc.dataclass
class _DirectorySyncRefused:
    """Refuse the directory sync the way macOS does.

    POSIX does not require ``fsync`` to accept a directory descriptor; macOS
    rejects it with ``EINVAL``. The temporary file's own sync must still run,
    so only a descriptor that ``os.fstat`` reports as a directory is refused.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    def fsync(self, descriptor: int) -> None:
        """Refuse a directory descriptor, syncing a file descriptor for real."""
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            message = "Invalid argument"
            raise OSError(errno.EINVAL, message)
        os.fsync(descriptor)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening."""
        return os.open(path, flags)

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing."""
        os.close(descriptor)


def test_a_refused_directory_sync_does_not_fail_a_committed_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported directory sync must not report a completed write as failed.

    ``temporary.replace`` runs before this sync, so the mutation is already
    committed by the time the directory descriptor is refused. Surfacing the
    refusal would make ``make duplication-allow`` exit non-zero having in fact
    rewritten ``pyproject.toml``. The file's own durability guarantee is
    unaffected: that sync has already succeeded on the temporary file.
    """
    destination = tmp_path / "config.toml"
    destination.write_bytes(b"original\n")
    monkeypatch.setattr(atomic_write, "os", _DirectorySyncRefused())

    atomic_write.atomic_write(
        destination,
        b"replacement\n",
        options=atomic_write.AtomicWriteOptions(sync_file=True),
    )

    assert destination.read_bytes() == b"replacement\n", (
        "A committed replacement must survive an unsupported directory sync."
    )
    assert list(tmp_path.glob(f".{destination.name}.*")) == [], (
        "A completed replacement must leave no temporary sibling behind."
    )


@dc.dataclass
class _FailingFileSync:
    """Fail the temporary file's ``fsync``, before the cleanup block runs.

    ``atomic_write`` creates the temporary file with ``delete=False``, so the
    file outlives its own close and only the cleanup path can remove it. The
    file sync happens inside the creation block, before cleanup is entered, so
    a failure here is the earliest observable point at which a temporary
    sibling exists with nothing yet arranged to delete it.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    def fsync(self, descriptor: int) -> None:
        """Fail the temporary file's sync."""
        message = "temporary file sync failed"
        raise OSError(message)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening; a failing sync never reaches this."""
        return os.open(path, flags)

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing."""
        os.close(descriptor)


def test_removes_the_temporary_file_when_its_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure while syncing the temporary file must not leak it."""
    destination = tmp_path / "config.toml"
    spy = _FailingFileSync()
    monkeypatch.setattr(atomic_write, "os", spy)

    with pytest.raises(OSError, match="temporary file sync failed"):
        atomic_write.atomic_write(
            destination,
            b"payload\n",
            options=atomic_write.AtomicWriteOptions(sync_file=True),
        )

    assert list(tmp_path.glob(f".{destination.name}.*")) == [], (
        "A failed temporary sync must not leave the temporary sibling behind."
    )
    assert not destination.exists(), (
        "A failed temporary sync must not create the destination."
    )


@dc.dataclass
class _FailingStream:
    """Wrap a temporary-file stream so one method raises on use.

    ``atomic_write`` records the temporary path before it writes anything, so
    the window these cases cover is the earliest one in which a sibling
    exists with the destination still untouched. Nothing else on the
    filesystem names that file, so a leak here is invisible to the caller
    beyond the error it already sees.
    """

    stream: typ.IO[bytes]
    method: str

    def __enter__(self) -> _FailingStream:
        """Enter the wrapped stream's context as this wrapper."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close the wrapped stream, letting any failure propagate."""
        self.stream.close()

    def __getattr__(self, name: str) -> object:
        """Fail the requested method, delegating everything else."""
        if name == self.method:

            def fail(*_args: object, **_kwargs: object) -> None:
                message = f"temporary file {self.method} failed"
                raise OSError(message)

            return fail
        return getattr(self.stream, name)


@pytest.mark.parametrize("method", ["write", "flush"])
def test_removes_the_temporary_file_when_an_early_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """Failing to write or flush the temporary file must not leak it.

    The sync-failure case above covers a fault after the stream has closed;
    these two cover the earlier ones. Each is asserted separately because
    ``flush`` is the point at which buffered content would otherwise be lost
    silently, and a cleanup path that handled only an outright write failure
    would pass a test that exercised just the first.
    """
    destination = tmp_path / "config.toml"
    destination.write_bytes(b"original\n")
    open_stream = atomic_write.tempfile.NamedTemporaryFile

    def failing(*args: object, **kwargs: object) -> _FailingStream:
        # ``object``-typed ``*args`` matches no ``NamedTemporaryFile`` overload,
        # even though the only call that reaches this double passes exactly the
        # two keywords ``atomic_write`` itself uses.
        admit_stream = typ.cast("typ.Any", open_stream)
        return _FailingStream(admit_stream(*args, **kwargs), method)

    monkeypatch.setattr(atomic_write.tempfile, "NamedTemporaryFile", failing)

    with pytest.raises(OSError, match=f"temporary file {method} failed"):
        atomic_write.atomic_write(destination, b"payload\n")

    assert list(tmp_path.glob(f".{destination.name}.*")) == [], (
        f"A failed {method} must not leave the temporary sibling behind."
    )
    assert destination.read_bytes() == b"original\n", (
        f"A failed {method} must leave the destination untouched."
    )


def test_syncs_the_temporary_file_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting a sync fsyncs the temporary file and the parent directory."""
    destination = tmp_path / "config.toml"
    spy = _OsSpy()
    monkeypatch.setattr(atomic_write, "os", spy)

    atomic_write.atomic_write(
        destination,
        b"payload\n",
        options=atomic_write.AtomicWriteOptions(sync_file=True),
    )

    assert len(spy.synced) == 2, "File and parent directory must each be fsynced."
    regular_files = [s for s in spy.synced if stat.S_ISREG(s.st_mode)]
    directories = [s for s in spy.synced if stat.S_ISDIR(s.st_mode)]
    assert len(regular_files) == 1, "Exactly one fsync must target the temporary file."
    assert len(directories) == 1, "Exactly one fsync must target the parent directory."
    assert destination.read_bytes() == b"payload\n", "The write must still complete."
