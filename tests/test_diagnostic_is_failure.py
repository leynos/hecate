"""Unit tests for the ``is_failure`` attribute of the exported diagnostics.

Both severity-carrying diagnostics answer one question: does this finding fail
the check? The rule is written once and bound into both classes, so the tests
here pin the public attribute rather than only the internal predicate, and pin
that the single shared descriptor still reads each instance it is asked about.
The unclassified-module policy that produces one of these diagnostics is
exercised separately in ``tests/test_unclassified_modules.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hecate.diagnostics import CoverageDiagnostic, UnclassifiedModuleDiagnostic
from hecate.policy import EdgeState, Severity


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (Severity.ERROR, True),
        (Severity.WARNING, False),
        (Severity.EXEMPT, False),
    ],
    ids=["error", "warning", "exempt"],
)
def test_exported_module_diagnostic_answers_is_failure(
    severity: Severity, *, expected: bool
) -> None:
    """``UnclassifiedModuleDiagnostic.is_failure`` is part of the public surface.

    The class is exported from ``hecate``, so a consumer can ask a diagnostic
    it holds whether the run fails. The predicate that decides it is defined
    once for both severity-carrying diagnostics; this pins the attribute the
    package promises, rather than only the internal call rule, so a refactor
    that deleted the property in favour of a free function would fail here
    instead of breaking a downstream caller with ``AttributeError``.
    """
    diagnostic = UnclassifiedModuleDiagnostic(
        module="pkg.newfeature",
        source_path=Path("pkg/newfeature/__init__.py"),
        severity=severity,
    )

    assert diagnostic.is_failure is expected, (
        f"severity {severity} must report is_failure={expected}, "
        f"got {diagnostic.is_failure}"
    )


def test_both_diagnostics_answer_is_failure_independently() -> None:
    """The shared descriptor must stay bound to its own owner.

    ``is_failure`` is one descriptor object referenced by two classes, so a
    slip that rebound it, or that made the rule read class state rather than
    the instance handed to it, would answer for whichever diagnostic was
    touched last. Asking each diagnostic after the other has been queried
    pins the answers to the instances rather than to a shared mutable owner.
    """
    failing = UnclassifiedModuleDiagnostic(
        module="pkg.newfeature",
        source_path=Path("pkg/newfeature/__init__.py"),
        severity=Severity.ERROR,
    )
    passing = CoverageDiagnostic(
        state=EdgeState.UNCLASSIFIED,
        severity=Severity.WARNING,
        rule_id="HEC001",
        importer="pkg.a",
        imported="pkg.b",
        source_path=Path("pkg/a.py"),
        line=1,
    )

    assert failing.is_failure is True, "An error severity must fail the check."
    assert passing.is_failure is False, (
        "A warning severity in another class must not inherit the first answer."
    )
    assert failing.is_failure is True, (
        "Querying a second diagnostic must not change the first one's answer."
    )
