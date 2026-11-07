"""Make the repository root importable for tests that exercise ``scripts/``."""

from __future__ import annotations

import sys
from pathlib import Path

from .release_scenario import fake  # noqa: F401 - pytest discovers the fixture here.

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
