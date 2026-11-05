"""Apply the house suppression convention to literal source text.

The convention itself lives in ``test_suppressions.violations``, and applying
it to the repository lives in the same module. Both of those read files, which
makes them awkward fixtures: a case that wants to exercise one rule has to
plant a file or reach into a module that scans the tree.

This module is the seam between the two. It takes text, runs it through the
same reader and the same rule function the repository scan uses, and returns
the messages. Fixture modules import this rather than reimplementing the call,
so a fixture cannot agree with a copy of the policy.
"""

from __future__ import annotations

from .suppressions import suppressions_in
from .test_suppressions import violations


def reported(source: str) -> list[str]:
    """Return the convention messages for every suppression in ``source``.

    Parameters
    ----------
    source : str
        Python source read as if it were a checked module. It is passed to
        the same reader and the same rules the repository scan uses, so a
        fixture cannot agree with a copy of the policy.

    Returns
    -------
    list[str]
        One message per broken rule, in source order. Empty means every
        suppression in the text follows the convention.

    """
    return [
        message
        for suppression in suppressions_in(source)
        for message in violations((suppression,))
    ]
