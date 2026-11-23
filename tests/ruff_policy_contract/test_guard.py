"""Cases: the partial-checkout guard must cover the caller's own files.

mutmut runs ``tests/`` against ``hecate/`` from a sandbox that need not carry
the repository root. The contract modules skip on a false guard result so a
mutation run reports mutation coverage rather than an unrelated ``IOError``.

The shared predicate covers the configuration and the sampled module, which
every contract reads. A module that also reads the lockfile, the Makefile or
the committed inventory needs those named too, or a checkout that carries the
first two and not the third raises out of a reader rather than skipping.

These cases are what make the guard's signature meaningful: without them a
predicate that ignored its arguments would still satisfy every caller, because
the real repository carries all of the files.
"""

from __future__ import annotations

from pathlib import Path

from .reading import repository_files_present


class TestCallerSpecificFiles:
    """A guard must report on every file it was asked about."""

    def test_a_missing_extra_file_makes_the_guard_false(self, tmp_path: Path) -> None:
        """The reported defect: an absent lockfile did not affect the result."""
        assert not repository_files_present(tmp_path / "absent.lock"), (
            "the guard ignored a file it was asked about, so a module reading "
            "it would raise FileNotFoundError instead of skipping"
        )

    def test_a_present_extra_file_does_not_make_the_guard_false(
        self, tmp_path: Path
    ) -> None:
        """An extra file that exists must not be treated as absent."""
        present = tmp_path / "present.txt"
        present.write_text("", encoding="utf-8")
        assert repository_files_present(present), (
            "the guard reported false for a file that exists, so a complete "
            "checkout would skip its contracts"
        )

    def test_the_shared_files_still_decide_without_extras(self) -> None:
        """Adding the parameter must not weaken the original check."""
        assert repository_files_present(), (
            "the repository carries the configuration and the sampled module, "
            "so the guard must still report true with no extras named"
        )
