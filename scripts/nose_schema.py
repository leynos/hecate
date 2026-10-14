"""Shared schema helpers and findings for the nose duplication gate.

This module owns the gate's error vocabulary, the gate-neutral finding
types, and the validation of the ``nose query --format json`` report.
``scripts/nose_detector.py`` drives the binary itself, and
``scripts/duplication_gate.py`` owns the reasoned allowlist and CLI.

The report is treated as untrusted input: it is produced by a separate
process whose version this gate verifies but does not control. Validating it
here keeps a surprising shape a single diagnosed configuration error rather
than an attribute error raised somewhere inside the matcher.

Every ``require_*`` helper below shares one contract, stated here rather than
repeated in each docstring: ``context`` names the configuration path being
read, a rejected value raises :exc:`GateConfigError` naming that path and the
shape it wanted, and an accepted value is returned in narrowed form so callers
can use it without re-checking. What each helper's own docstring adds is only
the predicate it applies and the reasoning behind it. Elements of a rejected
array are diagnosed against their own ``context[]`` path, not the array as a
whole.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ
from collections import abc as cabc
from pathlib import Path

#: The report layout this gate understands. nose bumps it when the payload
#: changes shape, so a mismatch means the pinned binary and the gate disagree.
#: Refusing to guess is what keeps an unnoticed version drift from silently
#: changing what the gate enforces. This is the one deliberate addition to the
#: reference schema module adopted from ``leynos/episodic``.
REPORT_SCHEMA_VERSION = 9

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "Finding",
    "GateConfigError",
    "GateExecutionError",
    "Location",
    "normalize_findings",
    "require_positive_int",
    "require_string",
    "require_string_tuple",
    "require_table",
]


class GateConfigError(ValueError):
    """Raised when the gate configuration or the detector report is malformed.

    ``label`` is the prefix the CLI prints before the message, so a rendered
    diagnostic reads ``<label>: <message>``. Naming the class of failure on the
    error itself keeps the CLI from having to re-derive it by type test at the
    point where it only wants to report.
    """

    label = "configuration error"


class GateExecutionError(GateConfigError):
    """Raised when the pinned detector is missing, wrong, or fails to run."""

    label = "tool error"


@dc.dataclass(frozen=True, slots=True)
class Location:
    """One duplicated region reported by nose.

    Attributes
    ----------
    file : str
        Repository-relative POSIX path of the duplicated region.
    start, end : int
        Inclusive first and last source line of the region.
    name : str | None
        Unit name when nose matched a whole function, class, or method;
        ``None`` for fragment-level matches such as import blocks.
    """

    file: str
    start: int
    end: int
    name: str | None

    @property
    def span(self) -> str:
        """Return the ``path:start-end`` span of this location."""
        return f"{self.file}:{self.start}-{self.end}"

    @property
    def label(self) -> str:
        """Return the span, suffixed with the unit name when nose named one."""
        return self.span if self.name is None else f"{self.span} {self.name}"


@dc.dataclass(frozen=True, slots=True)
class Finding:
    """One duplication family in gate-neutral form.

    Attributes
    ----------
    witness : str
        nose evidence kind (``exact``, ``copy-paste``, ``similar``, ...).
    value : float
        nose refactoring value; the gate reports it and orders by it.
    locations : tuple[Location, ...]
        Every duplicated region in the family, in report order.
    """

    witness: str
    value: float
    locations: tuple[Location, ...]

    @property
    def label(self) -> str:
        """Return the ``path:lines ~ path:lines`` summary of the family."""
        return " ~ ".join(location.label for location in self.locations)


def _reject(context: str, clause: str) -> typ.Never:
    """Raise the standard invalid-value diagnostic for ``context``.

    Every validator in this module reports the same way: name the offending
    configuration path, then say what it should have been. ``clause`` is the
    text that follows ``"must"``, so the message is always
    ``f"{context} must {clause}"``. Keeping that shape in one place stops the
    validators from drifting apart in wording, which matters because callers
    match on these messages.
    """
    msg = f"{context} must {clause}"
    raise GateConfigError(msg)


def require_table(value: object, *, context: str) -> cabc.Mapping[str, object]:
    """Validate one TOML table before configuration logic consumes it.

    Accepts any mapping whose keys are all strings. Keys are checked because
    the schema is read with ``str`` lookups, so a non-string key could not be
    reached by any later ``.get`` and would surface much later as a missing
    value rather than a malformed one.
    """
    if not isinstance(value, cabc.Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        _reject(context, "be a table with string keys")
    return typ.cast("cabc.Mapping[str, object]", value)


def require_string(value: object, *, context: str) -> str:
    """Validate one required non-empty configuration string.

    A key that is missing entirely arrives here as ``None`` and is rejected
    like any other non-string, so a value the configuration should have
    supplied is reported at its own path rather than silently defaulting.
    An empty string is rejected for the same reason: it is a present-but-unset
    typo, not an omission the gate should paper over.
    """
    if not _is_non_empty_string(value):
        _reject(context, "be a non-empty string")
    return value


def require_string_tuple(value: object, *, context: str) -> tuple[str, ...]:
    """Validate one configuration array of non-empty strings.

    Strings and bytes are rejected even though both are sequences of strings,
    because a scalar ``roots = "hecate"`` is a plausible mistake worth naming
    as such rather than silently iterating its characters.
    """
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        _reject(context, "be an array of strings")
    return tuple(require_string(item, context=f"{context}[]") for item in value)


def _is_non_empty_string(value: object) -> typ.TypeIs[str]:
    """Report whether ``value`` is a non-empty string."""
    return isinstance(value, str) and bool(value)


def _is_integer(value: object) -> typ.TypeIs[int]:
    """Report whether ``value`` is an integer rather than a boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def require_positive_int(value: object, *, context: str) -> int:
    """Validate one required positive configuration integer.

    A bool is rejected even though it subclasses ``int``, so a TOML ``true``
    is never read as a count of 1.
    """
    if not _is_integer(value) or value < 1:
        _reject(context, "be a positive integer")
    return value


def normalize_findings(report: object) -> list[Finding]:
    """Convert one validated nose report into ordered gate findings.

    Parameters
    ----------
    report : object
        Decoded ``nose query --format json`` report.

    Returns
    -------
    list[Finding]
        Findings ordered by descending value, then by source location.

    Raises
    ------
    GateConfigError
        If the report declares a different schema version or does not match
        the expected shape.
    """
    document = require_table(report, context="nose report")
    _require_supported_schema(document)
    families = document.get("families")
    if not isinstance(families, cabc.Sequence) or isinstance(families, (str, bytes)):
        msg = "nose report families must be an array"
        raise GateConfigError(msg)
    findings = [
        _finding(family, context=f"nose report families[{index}]")
        for index, family in enumerate(families)
    ]
    findings.sort(key=lambda finding: (-finding.value, finding.label))
    return findings


def _require_supported_schema(document: cabc.Mapping[str, object]) -> None:
    """Refuse a report whose declared schema version this gate predates."""
    version = document.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        msg = (
            f"nose report schema_version must be {REPORT_SCHEMA_VERSION}, "
            f"got {version!r}; the pinned detector and this gate disagree"
        )
        raise GateConfigError(msg)


def _finding_value(value: object, *, context: str) -> float:
    """Validate a family's refactoring value as a non-boolean number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject(f"{context}.value", "be a number")
    return float(value)


def _finding_locations(value: object, *, context: str) -> tuple[Location, ...]:
    """Validate a family's member locations, preserving their report order."""
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        _reject(f"{context}.locations", "be an array")
    if not value:
        msg = f"{context}.locations must not be empty"
        raise GateConfigError(msg)
    return tuple(
        _location(location, context=f"{context}.locations[{index}]")
        for index, location in enumerate(value)
    )


def _finding(raw: object, *, context: str) -> Finding:
    """Validate one nose family payload."""
    family = require_table(raw, context=context)
    return Finding(
        witness=require_string(family.get("witness"), context=f"{context}.witness"),
        value=_finding_value(family.get("value"), context=context),
        locations=_finding_locations(family.get("locations"), context=context),
    )


def _location(raw: object, *, context: str) -> Location:
    """Validate one nose location payload."""
    location = require_table(raw, context=context)
    start = require_positive_int(location.get("start"), context=f"{context}.start")
    end = location.get("end")
    if not _is_integer(end) or end < start:
        msg = f"{context}.end must not precede start"
        raise GateConfigError(msg)
    raw_name = location.get("name")
    name: str | None = None
    if raw_name is not None:
        if not _is_non_empty_string(raw_name):
            msg = f"{context}.name must be a non-empty string or null"
            raise GateConfigError(msg)
        name = raw_name
    return Location(
        file=Path(
            require_string(location.get("file"), context=f"{context}.file")
        ).as_posix(),
        start=start,
        end=end,
        name=name,
    )
