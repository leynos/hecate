"""Property tests for duplication-gate matching and normalization invariants."""

from __future__ import annotations

from duplication_gate_test_support import allowlist, detector, gate
from hypothesis import given
from hypothesis import strategies as st

_PATHS = st.sampled_from((
    "hecate/a.py",
    "hecate/b.py",
    "hecate/c.py",
    "hecate/d.py",
))
_NAMES = st.sampled_from(("alpha", "beta", None))


@st.composite
def _locations(draw: st.DrawFn) -> detector.Location:
    """Build one reported location with a stable span."""
    start = draw(st.integers(min_value=1, max_value=200))
    return detector.Location(
        file=draw(_PATHS),
        start=start,
        end=start + draw(st.integers(min_value=0, max_value=40)),
        name=draw(_NAMES),
    )


@st.composite
def _findings(draw: st.DrawFn) -> detector.Finding:
    """Build one duplication family over two or more locations."""
    return detector.Finding(
        witness=draw(st.sampled_from(("exact", "copy-paste", "similar"))),
        value=float(draw(st.integers(min_value=0, max_value=100))),
        locations=tuple(draw(st.lists(_locations(), min_size=2, max_size=5))),
    )


@st.composite
def _allow_entries(draw: st.DrawFn) -> allowlist.AllowEntry:
    """Build one valid unit or members allow entry."""
    keys = draw(
        st.one_of(
            st.tuples(_PATHS),
            st.lists(_PATHS, min_size=2, max_size=3, unique=True).map(tuple),
        )
    )
    return allowlist.AllowEntry(keys=keys, reason="property")


@given(finding=_findings(), entry=_allow_entries())
def test_entries_allow_only_fully_covered_families(
    finding: detector.Finding,
    entry: allowlist.AllowEntry,
) -> None:
    """An entry silences a family exactly when it covers every location."""
    covered = all(
        any(allowlist.key_matches(key, location) for key in entry.keys)
        for location in finding.locations
    )
    assert entry.matches(finding) is covered, (
        "Matching must require coverage of every reported location."
    )


def _shared_unit_name(finding: detector.Finding) -> str | None:
    """Return the one name every location shares, or ``None`` if there is none.

    A ``path::name`` key only matches a family whose locations all name the
    same unit, so this reports whether that form is even available. ``None``
    is also a name in the report, and a family mixing a named and an unnamed
    location has no shared name to key on.
    """
    names = {location.name for location in finding.locations}
    if names == {None} or len(names) != 1:
        return None
    return next(iter(names))


@st.composite
def _covered_family(
    draw: st.DrawFn,
) -> tuple[detector.Finding, allowlist.AllowEntry]:
    """Build a family together with an entry that covers every location.

    The entry is drawn from the family's own files, so the coverage
    precondition holds by construction rather than by filtering. When every
    location also shares one unit name, the entry may key on the qualified
    ``path::name`` form instead, which exercises the name half of the matcher.
    """
    finding = draw(_findings())
    files = tuple({location.file for location in finding.locations})
    name = _shared_unit_name(finding)
    prefer_qualified = name is not None and draw(st.booleans())
    keys = tuple(f"{path}::{name}" for path in files) if prefer_qualified else files
    return finding, allowlist.AllowEntry(keys=keys, reason="property")


@given(covered=_covered_family())
def test_a_new_member_outside_the_exception_blocks_again(
    covered: tuple[detector.Finding, allowlist.AllowEntry],
) -> None:
    """A covered family blocks again once an unlisted location joins it."""
    finding, entry = covered
    assert entry.matches(finding), (
        "The constructed entry must cover the family it was built from."
    )
    extended = detector.Finding(
        witness=finding.witness,
        value=finding.value,
        locations=(
            *finding.locations,
            detector.Location(
                file="hecate/unlisted.py",
                start=1,
                end=2,
                name=None,
            ),
        ),
    )

    assert not entry.matches(extended), (
        "A family reaching an unlisted file must keep blocking."
    )
    assert not entry.matches(
        detector.Finding(
            witness=finding.witness,
            value=finding.value,
            locations=(
                detector.Location(file="hecate/unlisted.py", start=1, end=2, name=None),
            ),
        )
    ), "A partial exception must never cover a family on its own."


@given(finding=_findings())
def test_file_keys_cover_their_own_locations(finding: detector.Finding) -> None:
    """Listing every file in a family always silences it."""
    entry = allowlist.AllowEntry(
        keys=tuple({location.file for location in finding.locations}),
        reason="property",
    )
    assert entry.matches(finding), (
        "An entry naming every participating file must silence the family."
    )


@given(
    findings=st.lists(_findings(), max_size=8),
    entries=st.lists(_allow_entries(), max_size=6),
)
def test_partition_conserves_findings_and_identifies_stale_entries(
    findings: list[detector.Finding],
    entries: list[allowlist.AllowEntry],
) -> None:
    """Every finding is exactly blocking or allowed and stale entries match none."""
    blocking, allowed, stale = gate.partition_findings(findings, entries)

    assert len(blocking) + len(allowed) == len(findings), (
        "Partitioning must retain every reported finding exactly once."
    )
    assert all(
        any(entry.matches(finding) for entry in entries) for finding in allowed
    ), "Allowed findings must have a matching allow entry."
    assert all(
        not any(entry.matches(finding) for entry in entries) for finding in blocking
    ), "Blocking findings must have no matching allow entry."
    assert all(
        not any(entry.matches(finding) for finding in findings) for entry in stale
    ), "Stale entries must not match any current finding."


@given(findings=st.lists(_findings(), min_size=1, max_size=8))
def test_normalization_orders_values_then_locations(
    findings: list[detector.Finding],
) -> None:
    """Normalized findings use the documented deterministic ordering."""
    normalized = detector.normalize_findings(_report_of(findings))
    assert len(normalized) == len(findings), (
        "Normalization must conserve the finding count."
    )
    sort_keys = [finding.order_key for finding in normalized]
    assert sort_keys == sorted(sort_keys), (
        "Normalization must sort by descending value, then location, then witness."
    )


def _report_of(findings: list[detector.Finding]) -> dict[str, object]:
    """Build the stub schema-9 report carrying ``findings`` in the given order."""
    return {
        "schema_version": 9,
        "families": [
            {
                "witness": finding.witness,
                "value": finding.value,
                "locations": [
                    {
                        "file": location.file,
                        "start": location.start,
                        "end": location.end,
                        "name": location.name,
                    }
                    for location in finding.locations
                ],
            }
            for finding in findings
        ],
    }


def _tied_family(witness: str) -> detector.Finding:
    """Build one of several families identical but for their witness.

    Every other field matches, so ``(-value, label)`` ties completely and only
    the witness can separate them. This is the fixed counterexample the
    verification plan pins: it is the smallest input on which a partial sort
    key leaves report order visible in the output.
    """
    return detector.Finding(
        witness=witness,
        value=10.0,
        locations=(
            detector.Location(file="hecate/a.py", start=1, end=9, name=None),
            detector.Location(file="hecate/b.py", start=1, end=9, name=None),
        ),
    )


def test_normalization_is_stable_for_families_that_tie_on_every_other_field() -> None:
    """Families differing only in witness must not take their report order.

    Without the witness tie-break this fails: the three families tie on
    ``(-value, label)``, so each input order is preserved and the three outputs
    differ from one another.
    """
    families = [_tied_family(name) for name in ("exact", "copy-paste", "similar")]
    shuffled = [families[2], families[1], families[0]]

    first = detector.normalize_findings(_report_of(families))
    second = detector.normalize_findings(_report_of(shuffled))

    assert first == second, (
        "Normalization must not depend on the order nose emitted the families."
    )
    assert [finding.witness for finding in first] == [
        "copy-paste",
        "exact",
        "similar",
    ], "The witness must break the tie in a fixed, asserted order."


@st.composite
def _colliding_findings(draw: st.DrawFn) -> detector.Finding:
    """Build a family whose sort key collides with its siblings'.

    Every family this draws shares one value, one location set, and a witness
    from a small pool, so a report of several of them ties on ``(-value,
    label)`` by construction. A strategy that drew values freely would rarely
    produce a tie, and the shuffle assertion below would then pass without ever
    exercising the property it exists to check.
    """
    return detector.Finding(
        witness=draw(st.sampled_from(("exact", "copy-paste", "similar"))),
        value=10.0,
        locations=(
            detector.Location(file="hecate/a.py", start=1, end=9, name=None),
            detector.Location(file="hecate/b.py", start=1, end=9, name=None),
        ),
    )


@st.composite
def _shuffle_inputs(
    draw: st.DrawFn,
) -> tuple[list[detector.Finding], list[allowlist.AllowEntry]]:
    """Draw findings and entries, biased towards colliding sort keys."""
    findings = draw(
        st.one_of(
            st.lists(_findings(), min_size=1, max_size=8),
            st.lists(_colliding_findings(), min_size=2, max_size=5),
        )
    )
    return findings, draw(st.lists(_allow_entries(), max_size=6))


@given(inputs=_shuffle_inputs(), data=st.data())
def test_partition_and_normalization_survive_input_permutation(
    inputs: tuple[list[detector.Finding], list[allowlist.AllowEntry]],
    data: st.DataObject,
) -> None:
    """Partitioning and normalizing are invariant under a shuffle of the inputs."""
    findings, entries = inputs
    shuffled_findings = data.draw(st.permutations(findings))
    shuffled_entries = data.draw(st.permutations(entries))

    ordered = gate.partition_findings(findings, list(entries))
    shuffled = gate.partition_findings(list(shuffled_findings), list(shuffled_entries))

    def as_sets(
        triple: tuple[
            list[detector.Finding], list[detector.Finding], list[allowlist.AllowEntry]
        ],
    ) -> tuple[set[detector.Finding], set[detector.Finding], set[allowlist.AllowEntry]]:
        return (set(triple[0]), set(triple[1]), set(triple[2]))

    assert as_sets(ordered) == as_sets(shuffled), (
        "A shuffle of the report and the allow list must not change the partition."
    )
    assert detector.normalize_findings(_report_of(shuffled_findings)) == (
        detector.normalize_findings(_report_of(findings))
    ), "A shuffle of the report must not change the normalized order."


def test_the_normalization_shuffle_case_is_not_vacuous() -> None:
    """The permutation property is exercised on a non-trivial tied example.

    The generator above can produce single-family reports, where a permutation
    is the identity and the assertion cannot fail. This pins one input where
    the shuffle genuinely reorders, so the property above cannot pass merely by
    drawing trivial cases.
    """
    families = [_tied_family(name) for name in ("exact", "copy-paste", "similar")]
    report = _report_of(families)

    assert list(reversed(families)) != families, "The witness order must reorder."
    assert detector.normalize_findings(_report_of(list(reversed(families)))) == (
        detector.normalize_findings(report)
    ), "The reordered report must still normalize to the same sequence."
