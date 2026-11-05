"""Contracts over the Ruff preview-adoption policy.

``pyproject.toml`` selects prefixes such as ``D`` and ``RUF`` and adopts
preview rules one code at a time. Neither half is visible in review as a
list: the prefixes cover whatever upstream considers stable, and the adopted
codes are spread over a 120-line ``extend-select``. The selected set, which
is what the gate draws from, exists only inside Ruff's own resolution.

The inventory in ``tests/ruff_policy_contract/enabled_rules.txt`` records that
resolved selection for the pinned binary, and the tests here compare it
against what Ruff reports now, in both directions. An addition is lint policy
nobody reviewed; a removal is house policy that quietly stopped running.
Per-file ignores are a separate setting and are not part of this inventory, so
a rule listed here may still be ignored on a particular path. The readers live
in ``reading.py`` so the rule tests apply them to the real files while the
cases in ``test_reading.py`` apply them to text this repository does not
contain.

``discovery.py`` holds the readers that decide *which* configuration applies
to a file. The inventory is one row, and it describes the whole tree only
while no subdirectory carries a config of its own, so those readers answer a
question about the gate's reach rather than about the rule selection.
"""
