"""Replace files atomically through a temporary sibling.

A neutral persistence helper used by the duplication allowlist writer and the
spelling-cache helper. It belongs to no caller's domain: the
write-temporary-then-``Path.replace`` sequence with its knobs is wanted by more
than one tool, so the routine lives on its own rather than inside whichever
module needed it first.
"""

from __future__ import annotations

import contextlib
import dataclasses as dc
import os
import pathlib
import tempfile
import typing as typ

if typ.TYPE_CHECKING:
    from collections import abc as cabc

__all__ = ["AtomicWriteOptions", "atomic_write"]


@dc.dataclass(frozen=True, slots=True)
class AtomicWriteOptions:
    """Configure atomic replacement behaviour."""

    create_parents: bool = True
    preserve_mode: bool = False
    sync_file: bool = False


# Read as the default for `atomic_write` rather than constructed at each call
# site, which would evaluate the call in the signature and share one mutable
# default across every caller.
_DEFAULT_OPTIONS = AtomicWriteOptions()


@contextlib.contextmanager
def _open_directory(directory: pathlib.Path) -> cabc.Iterator[int]:
    """Open a directory descriptor for a scoped operation.

    Reading a directory needs O_RDONLY, which is not portable to Python's
    buffered ``open``; the raw descriptor is yielded so the caller's work runs
    between the open and the guaranteed close. A failure in ``os.open`` itself
    leaves no descriptor to release.

    Yields
    ------
    int
        The open directory descriptor.
    """
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def atomic_write(
    path: pathlib.Path,
    content: bytes,
    *,
    options: AtomicWriteOptions = _DEFAULT_OPTIONS,
) -> None:
    """Atomically replace a path after writing a temporary sibling.

    Parameters
    ----------
    path : pathlib.Path
        Destination to replace.
    content : bytes
        Complete replacement contents.
    options : AtomicWriteOptions
        Directory creation, mode preservation, and fsync policy. The default
        creates missing parents, ignores the destination mode, and does not
        fsync.
    """
    if options.create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if options.preserve_mode and path.exists() else None
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, dir=path.parent, prefix=f".{path.name}."
        ) as stream:
            # The temporary path is recorded the moment it exists, before
            # anything else can fail. The file was created with delete=False,
            # so it outlives its own close; a failure during the write, the
            # flush, or the sync would otherwise leave it behind, and the
            # finally block below could not even name the file to remove.
            temporary = pathlib.Path(stream.name)
            stream.write(content)
            stream.flush()
            if options.sync_file:
                os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(path)
        if options.sync_file:
            with _open_directory(path.parent) as descriptor:
                os.fsync(descriptor)
    finally:
        # A completed replacement has already moved this file, so a missing
        # path here is the success case as well as a retried cleanup.
        if temporary is not None:
            temporary.unlink(missing_ok=True)
