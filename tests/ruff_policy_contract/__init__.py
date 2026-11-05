"""Contracts over the Ruff preview-adoption policy.

``pyproject.toml`` selects prefixes such as ``D`` and ``RUF`` and adopts
preview rules one code at a time. Neither half is visible in review as a
list: the prefixes cover whatever upstream considers stable, and the adopted
codes are spread over a 120-line ``extend-select``. The effective set, which
is what the gate actually enforces, exists only inside Ruff's own resolution.

The inventory in ``tests/ruff_policy_contract/enabled_rules.txt`` records that
resolved set for the pinned binary, and the tests here compare it against what
Ruff reports now, in both directions. An addition is lint policy nobody
reviewed; a removal is house policy that quietly stopped running. The readers
live in ``reading.py`` so the rule tests apply them to the real files while
the cases in ``test_reading.py`` apply them to text this repository does not
contain.
"""
