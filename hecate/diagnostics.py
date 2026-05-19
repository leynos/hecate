"""Stable architecture diagnostics."""

from __future__ import annotations

import dataclasses as dc
from pathlib import Path


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
        payload = diagnostic_identity_to_dict(
            self.rule_id, self.importer, self.imported, self.line
        )
        payload["importer_group"] = self.importer_group
        payload["imported_group"] = self.imported_group
        payload["source_path"] = str(self.source_path)
        return payload


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
            "importer": self.importer,
            "imported": self.imported,
            "reason": self.reason,
        }
