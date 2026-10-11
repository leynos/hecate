"""Expose the duplication-gate modules to their focused tests.

The gate modules live in ``scripts/`` beside the repository's other tooling
rather than in the ``hecate`` package, so the tests import them by top-level
module name. Appending the directory (rather than prepending it) keeps the
application's own import paths ahead of it; nothing here shadows a
distribution module.
"""

import sys
from pathlib import Path

GATE_SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[1]
if str(GATE_SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.append(str(GATE_SCRIPTS_DIRECTORY))
