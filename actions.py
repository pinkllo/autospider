"""Compatibility shim for legacy imports.

This repo uses a src/ layout. Prefer importing from:
  - autospider.common.browser.actions.ActionExecutor

This file is kept so older scripts that import `actions.py` keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autospider.common.browser.actions import ActionExecutor  # noqa: E402

__all__ = ["ActionExecutor"]

