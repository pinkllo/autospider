from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    UpdateSkillStatsInput,
    UpdateSkillStatsResultDTO,
    to_skill_document_dto,
)
from autospider.contexts.experience.application.use_cases._result_support import (
    failed_result,
    require_trace_id,
)
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.result import ResultEnvelope


class UpdateSkillStats:
    def __init__(self, service: SkillDocumentService | None = None) -> None:
        self._service = service or SkillDocumentService()

    async def run(
        self, command: UpdateSkillStatsInput
    ) -> ResultEnvelope[UpdateSkillStatsResultDTO]:
        trace_id = require_trace_id()
        try:
            updated = self._service.update_skill_stats(
                document=command.document,
                status=command.status,
                success_rate=command.success_rate,
                success_rate_text=command.success_rate_text,
            )
        except ValueError as exc:
            return failed_result(
                trace_id,
                code="experience.update_stats_failed",
                message=str(exc),
            )
        data = UpdateSkillStatsResultDTO(updated_document=to_skill_document_dto(updated))
        return ResultEnvelope.success(data=data, trace_id=trace_id)
