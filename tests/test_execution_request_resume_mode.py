from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.composition.legacy.pipeline.types import ExecutionRequest, ResumeMode


@pytest.mark.parametrize(
    ("raw_resume_mode", "expected"),
    [
        (ResumeMode.FRESH, ResumeMode.FRESH),
        (ResumeMode.RESUME, ResumeMode.RESUME),
    ],
)
def test_execution_request_accepts_resume_mode_enum_input(
    raw_resume_mode: ResumeMode,
    expected: ResumeMode,
) -> None:
    request = ExecutionRequest.from_params({"resume_mode": raw_resume_mode})

    assert request.resume_mode is expected
