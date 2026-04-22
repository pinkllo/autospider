from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    SedimentSkillInput,
    SedimentSkillResultDTO,
    to_skill_document_dto,
)
from autospider.contexts.experience.application.use_cases._result_support import (
    failed_result,
    require_trace_id,
)
from autospider.contexts.experience.domain.ports import SkillRepository
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.result import ResultEnvelope


class SedimentSkill:
    def __init__(
        self,
        repository: SkillRepository,
        service: SkillDocumentService | None = None,
    ) -> None:
        self._repository = repository
        self._service = service or SkillDocumentService()

    async def run(self, command: SedimentSkillInput) -> ResultEnvelope[SedimentSkillResultDTO]:
        trace_id = require_trace_id()
        try:
            document = self._service.build_skill_document(
                domain=command.domain,
                name=command.name,
                description=command.description,
                list_url=command.list_url,
                task_description=command.task_description,
                fields={field.name: field for field in command.fields},
                status=command.status,
                success_count=command.success_count,
                total_count=command.total_count,
                frontmatter=command.frontmatter,
                title=command.title,
                insights_markdown=command.insights_markdown,
            )
            path = self._repository.save_document(
                command.domain,
                document,
                overwrite_existing=command.overwrite_existing,
            )
        except ValueError as exc:
            return failed_result(trace_id, code="experience.sediment_failed", message=str(exc))
        data = SedimentSkillResultDTO(path=path, document=to_skill_document_dto(document))
        return ResultEnvelope.success(data=data, trace_id=trace_id)
