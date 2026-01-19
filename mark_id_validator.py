"""Compatibility shim for legacy imports.

Prefer importing from:
  - autospider.extractor.validator.mark_id_validator
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autospider.extractor.validator.mark_id_validator import (  # noqa: E402
    MarkIdValidationResult,
    MarkIdValidator,
)

__all__ = ["MarkIdValidator", "MarkIdValidationResult"]

