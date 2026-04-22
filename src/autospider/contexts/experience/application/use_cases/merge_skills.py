from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    MergeSkillsInput,
    MergeSkillsResultDTO,
    to_skill_document_dto,
)
from autospider.contexts.experience.application.use_cases._result_support import (
    failed_result,
    require_trace_id,
)
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.result import ResultEnvelope


class MergeSkills:
    def __init__(self, service: SkillDocumentService | None = None) -> None:
        self._service = service or SkillDocumentService()

    async def run(self, command: MergeSkillsInput) -> ResultEnvelope[MergeSkillsResultDTO]:
        trace_id = require_trace_id()
        try:
            merged = self._service.merge_skill_documents(
                existing=command.existing_document,
                incoming=command.incoming_document,
            )
        except ValueError as exc:
            return failed_result(
                trace_id,
                code="experience.merge_failed",
                message=str(exc),
            )
        data = MergeSkillsResultDTO(merged_document=to_skill_document_dto(merged))
        return ResultEnvelope.success(data=data, trace_id=trace_id)
