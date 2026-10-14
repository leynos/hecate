#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.14"
# dependencies = ["cyclopts==4.25.2", "tomlkit==0.15.1"]
# ///
"""Blocking code-duplication gate over the pinned nose detector.

The gate runs the pinned ``nose`` binary with the repository's ``[tool.nose]``
settings, removes families covered by reasoned ``[tool.duplication_gate]``
allow entries, and fails while unsuppressed families remain. Stale allow
entries are reported so that resolved duplication does not leave dead
configuration behind.

``scripts/duplication_allowlist.py`` documents the allow-entry key syntax
and matching rules; ``scripts/nose_detector.py`` owns the detector itself.

The script is pinned to CPython 3.14 with the versions above because the gate
must produce the same verdict on a developer machine and in CI; ``make
duplication`` and ``make duplication-test`` both select that interpreter
explicitly. POSIX advisory locking (``fcntl.flock``) is used to serialize
concurrent ``make duplication-allow`` runs, so this workflow is supported on
POSIX hosts, including WSL.
"""

from __future__ import annotations

import sys
import tomllib
from collections import abc as cabc
from pathlib import Path

import cyclopts
from duplication_allowlist import (
    AllowEntry,
    append_allow_entry,
    load_allowlist,
    validate_key,
)
from nose_detector import PYPROJECT, load_settings, run_detector
from nose_schema import Finding, GateConfigError, GateExecutionError

app = cyclopts.App(help="Run or configure the code-duplication gate.")

type AllowlistReader = cabc.Callable[[Path], tuple[AllowEntry, ...]]
type FindingDetector = cabc.Callable[[], list[Finding]]


def partition_findings(
    findings: cabc.Sequence[Finding],
    allowlist: cabc.Sequence[AllowEntry],
) -> tuple[list[Finding], list[Finding], list[AllowEntry]]:
    """Split findings into blocking and allowed, and spot stale entries.

    Parameters
    ----------
    findings : collections.abc.Sequence[Finding]
        Normalized detector findings.
    allowlist : collections.abc.Sequence[AllowEntry]
        Reasoned exceptions from the repository configuration.

    Returns
    -------
    tuple[list[Finding], list[Finding], list[AllowEntry]]
        Blocking findings, silenced findings, and allow entries that no
        longer cover any finding.
    """
    blocking: list[Finding] = []
    allowed: list[Finding] = []
    used: set[int] = set()
    for finding in findings:
        matched = False
        for position, entry in enumerate(allowlist):
            if entry.matches(finding):
                used.add(position)
                matched = True
        (allowed if matched else blocking).append(finding)
    stale = [entry for position, entry in enumerate(allowlist) if position not in used]
    return blocking, allowed, stale


def detect_findings() -> list[Finding]:
    """Run the pinned detector with the repository's ``[tool.nose]`` settings.

    Returns
    -------
    list[Finding]
        Normalized duplication families emitted by the pinned detector.

    Notes
    -----
    Configuration and execution errors from the settings loader and detector
    propagate to the CLI boundary.
    """
    return run_detector(load_settings(PYPROJECT))


def _report(
    blocking: list[Finding], allowed: list[Finding], stale: list[AllowEntry]
) -> None:
    """Print the gate outcome in a concise, actionable form."""
    for entry in stale:
        joined = " ~ ".join(entry.keys)
        # The scan is bounded by `top`, so an entry this gate cannot match may
        # still be silencing duplication that is merely outside the reported
        # ranking. Saying it is "gone" would assert more than the run observed
        # and would invite deleting an entry that is still load-bearing.
        print(
            f"stale allow entry ({joined}): unmatched in this scan; "
            "widen the scan (raise `top`, or lower `min-size`) before deleting "
            "the entry, because the duplication it silenced may be gone, or its "
            "family may have changed shape"
        )
    if not blocking:
        suffix = f"; {len(allowed)} allowed by reasoned exceptions" if allowed else ""
        print(f"duplication gate passed{suffix}")
        return
    print(f"duplicate code: {len(blocking)} unsuppressed family/families")
    for finding in blocking:
        print(f"  {finding.label} ({finding.witness}, value {finding.value:.1f})")
    print(
        "Extract the shared logic into one helper, or record a considered "
        "exception:\n  make duplication-allow FIRST='<path[::name]>' "
        "[SECOND='<path[::name]>'] REASON='<why this stays>'"
    )


def _translate[T](
    action: cabc.Callable[[], T],
    *,
    label: str,
    execution_faults: tuple[type[BaseException], ...] = (),
    config_faults: tuple[type[BaseException], ...] = (),
) -> T:
    """Run ``action``, turning dependency failures into diagnosed gate errors.

    The two loaders below fail in the same three ways, so the policy for
    reporting them lives here once. A ``GateConfigError`` raised by ``action``
    is already the gate's own diagnosis and propagates unchanged; an
    ``execution_fault`` names the surrounding environment -- a missing binary,
    an unreadable file -- and becomes a ``GateExecutionError`` under ``label``;
    a ``config_fault`` names data the action was handed and becomes a
    ``GateConfigError`` carrying the dependency's own message.
    """
    try:
        return action()
    except GateConfigError:
        raise
    except execution_faults as error:
        msg = f"{label}: {error}"
        raise GateExecutionError(msg) from error
    except config_faults as error:
        raise GateConfigError(str(error)) from error


def _read_allowlist(reader: AllowlistReader) -> tuple[AllowEntry, ...]:
    """Read the reasoned allowlist, naming unreadable configuration.

    A malformed TOML file is an environment fault rather than a policy one:
    the repository configuration could not be read at all, which is a
    different repair from an entry that is readable but wrong.
    """
    return _translate(
        lambda: reader(PYPROJECT),
        label="cannot load duplication allowlist",
        execution_faults=(OSError, tomllib.TOMLDecodeError),
    )


def _detect_findings(detector: FindingDetector) -> list[Finding]:
    """Run the detector, separating execution failures from bad configuration.

    A ``TypeError`` or ``ValueError`` out of the detector means the report it
    produced is not the shape the gate understands, which is a configuration
    fault the maintainer resolves rather than an environment one.
    """
    return _translate(
        detector,
        label="nose detector failed",
        execution_faults=(OSError,),
        config_faults=(TypeError, ValueError),
    )


def _check_inputs(
    *,
    allowlist_reader: AllowlistReader,
    detector: FindingDetector,
) -> tuple[tuple[AllowEntry, ...], list[Finding]]:
    """Load the gate inputs with explicit local-environment failures."""
    return (_read_allowlist(allowlist_reader), _detect_findings(detector))


def _require_covered(finding: Finding | None, keys: tuple[str, ...]) -> None:
    """Refuse an exception that does not cover a whole reported family."""
    if finding is None:
        joined = " ~ ".join(keys)
        msg = (
            f"{joined} covers no reported family; record an exception only for "
            "duplication the detector currently reports, and check the key's "
            "spelling and its file glob against `make duplication`"
        )
        raise GateConfigError(msg)


def _covered_family(findings: list[Finding], keys: tuple[str, ...]) -> Finding | None:
    """Return the reported family these keys cover, if there is exactly one.

    Coverage is the same all-or-nothing rule the blocking gate applies, so this
    uses the entry's own matcher rather than re-implementing it: an approach
    that accepted a key set covering only part of a family would record an
    exception the gate then ignores, which reads as success while changing
    nothing.
    """
    candidate = AllowEntry(keys=keys, reason="validating")
    return next((finding for finding in findings if candidate.matches(finding)), None)


@app.command
def check() -> None:
    """Run the blocking duplication gate and exit non-zero on findings.

    The command reads the repository's fixed ``pyproject.toml`` path and the
    detector executes with an explicit repository working directory; it does
    not mutate the caller's process directory.

    Raises
    ------
    SystemExit
        With status 1 for blocking findings or status 2 for malformed
        configuration or a detector that cannot run.
    """
    try:
        allowlist, findings = _check_inputs(
            allowlist_reader=load_allowlist,
            detector=detect_findings,
        )
    except GateConfigError as error:
        print(f"{error.label}: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    blocking, allowed, stale = partition_findings(findings, allowlist)
    _report(blocking, allowed, stale)
    if blocking:
        raise SystemExit(1)


@app.command
def allow(
    *,
    first: str,
    second: list[str] | None = None,
    reason: str,
) -> None:
    """Record one reasoned exception in ``[tool.duplication_gate]``.

    The detector runs before anything is written, so an entry is recorded only
    once its keys are shown to cover a family the gate currently reports.
    Without that check a misspelled key, or a key set reaching only part of a
    family, would print a success message and change nothing: the gate would go
    on blocking exactly as before, while the recorded exception looked like an
    adjudication that had been applied.

    Parameters
    ----------
    first : str
        Location key (``path`` or ``path::name``) of the first or only member.
    second : list[str] | None
        Further location keys; when supplied, the entry silences only families
        whose every location matches one of the listed keys. Repeat the option
        for a family with more than two members; the keys are never joined into
        one value.
    reason : str
        Reviewable justification for keeping the duplication.

    Raises
    ------
    SystemExit
        If the reason is empty, a location key is malformed, or the keys do not
        cover a family in the current report.
    """
    if not reason.strip():
        print("REASON must not be empty", file=sys.stderr)
        raise SystemExit(2)
    keys = (first, *(second or ()))
    try:
        for key in keys:
            validate_key(key, context=f"'{key}'")
        _require_covered(_covered_family(_detect_findings(detect_findings), keys), keys)
        append_allow_entry(PYPROJECT, keys=keys, reason=reason)
    except (GateConfigError, OSError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(f"recorded duplication exception for {' ~ '.join(keys)}")


if __name__ == "__main__":
    app()
