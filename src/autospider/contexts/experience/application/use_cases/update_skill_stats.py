from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    UpdateSkillStatsInput,
    UpdateSkillStatsResultDTO,
    to_domain_skill_document,
    to_skill_document_dto,
)
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class UpdateSkillStats:
    def __init__(self, service: SkillDocumentService | None = None) -> None:
        self._service = service or SkillDocumentService()

    async def run(self, command: UpdateSkillStatsInput) -> ResultEnvelope[UpdateSkillStatsResultDTO]:
        trace_id = _require_trace_id()
        try:
            document = to_domain_skill_document(command.document)
            updated = self._service.update_skill_stats(
                document=document,
                status=command.status,
                success_rate=command.success_rate,
                success_rate_text=command.success_rate_text,
            )
        except ValueError as exc:
            return _failed(trace_id, code="experience.update_stats_failed", message=str(exc))
        data = UpdateSkillStatsResultDTO(updated_document=to_skill_document_dto(updated))
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
) -> ResultEnvelope[UpdateSkillStatsResultDTO]:
    error = ErrorInfo(kind="domain", code=code, message=message)
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])
