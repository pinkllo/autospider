from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    MergeSkillsInput,
    MergeSkillsResultDTO,
    to_domain_skill_document,
    to_skill_document_dto,
)
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class MergeSkills:
    def __init__(self, service: SkillDocumentService | None = None) -> None:
        self._service = service or SkillDocumentService()

    async def run(self, command: MergeSkillsInput) -> ResultEnvelope[MergeSkillsResultDTO]:
        trace_id = _require_trace_id()
        try:
            existing = to_domain_skill_document(command.existing_document)
            incoming = to_domain_skill_document(command.incoming_document)
            merged = self._service.merge_skill_documents(existing=existing, incoming=incoming)
        except ValueError as exc:
            return _failed(trace_id, code="experience.merge_failed", message=str(exc))
        data = MergeSkillsResultDTO(merged_document=to_skill_document_dto(merged))
        return ResultEnvelope.success(data=data, trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def _failed(
    trace_id: str,
    *,
    code: str,
    message: str,
) -> ResultEnvelope[MergeSkillsResultDTO]:
    error = ErrorInfo(kind="domain", code=code, message=message)
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])
