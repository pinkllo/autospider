from __future__ import annotations

from pathlib import Path
from typing import Any


class GraphHarnessError(RuntimeError):
    """Base error for GraphRunner E2E harness failures."""


class InterruptHandlingError(GraphHarnessError):
    """Raised when the harness cannot continue an interrupted graph run."""


class OutputArtifactError(GraphHarnessError):
    """Raised when merged graph outputs cannot be resolved or loaded."""


class UnsupportedInterruptError(InterruptHandlingError):
    """Raised for interrupts that must fail the E2E run immediately."""

    def __init__(self, interrupt_type: str, payload: dict[str, Any]) -> None:
        message = f"unsupported interrupt during E2E run: {interrupt_type}"
        super().__init__(message)
        self.interrupt_type = interrupt_type
        self.payload = payload


class MissingClarificationAnswerError(InterruptHandlingError):
    """Raised when a case does not provide enough clarification answers."""

    def __init__(self, *, question: str, index: int) -> None:
        message = f"missing clarification answer at index={index}: {question}"
        super().__init__(message)
        self.question = question
        self.index = index


class MissingOutputArtifactError(OutputArtifactError):
    """Raised when a required merged output file does not exist."""

    def __init__(self, *, label: str, path: Path) -> None:
        super().__init__(f"missing required output artifact: {label} -> {path}")
        self.label = label
        self.path = path
