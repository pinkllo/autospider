"""Compatibility shim for legacy imports.

Prefer importing from:
  - autospider.common.protocol
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autospider.common.protocol import *  # type: ignore  # noqa: F403,E402

