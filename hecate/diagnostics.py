"""Stable architecture diagnostics."""

from __future__ import annotations

import dataclasses as dc
import typing as typ
from pathlib import Path

from .policy import EdgeState, Severity


class _ClassifiedEdge(typ.Protocol):
    """The fields shared by diagnostics describing one classified import edge.

    Declared as read-only properties so a frozen dataclass with a narrower
    attribute type, such as a required ``str`` where this protocol allows
    ``None``, still satisfies it.
    """

    @property
    def rule_id(self) -> str: ...

    @property
    def importer(self) -> str: ...

    @property
    def imported(self) -> str: ...

    @property
    def line(self) -> int: ...

    @property
    def source_path(self) -> Path: ...

    @property
    def importer_group(self) -> str | None: ...

    @property
    def imported_group(self) -> str | None: ...


@dc.dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    """A forbidden import between two classified architecture groups."""

    rule_id: str
    importer: str
    imported: str
    importer_group: str
    imported_group: str
    source_path: Path
    line: int

    def identity(self) -> tuple[str, str, str, int]:
        """Return the stable identity used for sorting and de-duplication."""
        return (self.rule_id, self.importer, self.imported, self.line)

    def render(self) -> str:
        """Render a deterministic single-line diagnostic."""
        return (
            f"{self.rule_id}: {self.importer}:{self.line} imports forbidden "
            f"module {self.imported} "
            f"({self.importer_group} -> {self.imported_group})"
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic mapping."""
        return _classified_payload(
            self, state=EdgeState.FORBIDDEN, severity=Severity.ERROR
        )


def diagnostic_identity_to_dict(
    rule_id: str, importer: str, imported: str, line: int
) -> dict[str, object]:
    """Return the primitive identity fields as a JSON-safe mapping."""
    assert rule_id
    assert importer
    assert imported
    assert line >= 0
    return {
        "rule_id": rule_id,
        "importer": importer,
        "imported": imported,
        "line": line,
    }


def _classified_payload(
    diagnostic: _ClassifiedEdge, *, state: EdgeState, severity: Severity
) -> dict[str, object]:
    """Return the JSON-safe mapping shared by classified edge diagnostics.

    Both diagnostic kinds describe one evaluated edge, so they agree on the
    identity fields, the outcome state and severity, the optional group
    labels, and the source path. They differ only in ``render``, which is why
    the payload is built once here rather than per subclass.
    """
    payload = diagnostic_identity_to_dict(
        diagnostic.rule_id, diagnostic.importer, diagnostic.imported, diagnostic.line
    )
    payload["state"] = state.value
    payload["severity"] = severity.value
    payload["importer_group"] = diagnostic.importer_group
    payload["imported_group"] = diagnostic.imported_group
    payload["source_path"] = str(diagnostic.source_path)
    return payload


@dc.dataclass(frozen=True, slots=True)
class IgnoredImportDiagnostic:
    """A matched configured ignore entry."""

    importer: str
    imported: str
    reason: str

    def render(self) -> str:
        """Render a deterministic ignored-import line."""
        return f"ignored: {self.importer} -> {self.imported} ({self.reason})"

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe ignored-import mapping."""
        return {
            "state": EdgeState.EXEMPTED.value,
            "severity": Severity.EXEMPT.value,
            "importer": self.importer,
            "imported": self.imported,
            "reason": self.reason,
        }


@dc.dataclass(frozen=True, slots=True)
class CoverageDiagnostic:
    """An import edge that Hecate could not fully evaluate.

    These cover the states that previously vanished silently: an endpoint that
    matched no configured group, or a target that resolved to no known module.
    """

    state: EdgeState
    severity: Severity
    rule_id: str
    importer: str
    imported: str
    source_path: Path
    line: int
    importer_group: str | None = None
    imported_group: str | None = None

    @property
    def is_failure(self) -> bool:
        """Return whether this diagnostic fails the check."""
        return self.severity is Severity.ERROR

    def identity(self) -> tuple[str, str, str, str, int]:
        """Return the stable identity used for sorting and de-duplication."""
        return (
            self.state.value,
            self.importer,
            self.imported,
            str(self.source_path),
            self.line,
        )

    def render(self) -> str:
        """Render a deterministic single-line diagnostic."""
        groups = ""
        if self.importer_group is not None or self.imported_group is not None:
            # An unresolved side is shown as "?" so a one-sided match stays
            # readable without pretending the other endpoint was classified.
            importer_label = self.importer_group or "?"
            imported_label = self.imported_group or "?"
            groups = f" ({importer_label} -> {imported_label})"
        return (
            f"{self.rule_id}: {self.importer}:{self.line} {self.state.value} "
            f"import of {self.imported}{groups}"
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic mapping."""
        return _classified_payload(self, state=self.state, severity=self.severity)
