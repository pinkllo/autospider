from __future__ import annotations

from autospider.contexts.planning.application.dto import (
    ClassifyProtocolViolationInput,
    ClassifyRuntimeExceptionInput,
    FailureSignalDTO,
)
from autospider.contexts.planning.domain.policies import FailureClassifier
from autospider.platform.shared_kernel.result import ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class ClassifyRuntimeException:
    def __init__(self, classifier: FailureClassifier | None = None) -> None:
        self._classifier = classifier or FailureClassifier()

    def run(self, command: ClassifyRuntimeExceptionInput) -> ResultEnvelope[FailureSignalDTO]:
        trace_id = _require_trace_id()
        payload = self._classifier.classify_runtime_exception(
            component=command.component,
            error=command.error,
        )
        return ResultEnvelope.success(data=FailureSignalDTO(**payload), trace_id=trace_id)

    def classify_protocol_violation(
        self,
        command: ClassifyProtocolViolationInput,
    ) -> ResultEnvelope[FailureSignalDTO]:
        trace_id = _require_trace_id()
        payload = self._classifier.classify_protocol_violation(
            component=command.component,
            diagnostics=command.diagnostics,
        )
        return ResultEnvelope.success(data=FailureSignalDTO(**payload), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id
