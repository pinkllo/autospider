from __future__ import annotations

from autospider.contexts.experience.application.dto import (
    LookupSkillInput,
    LookupSkillResultDTO,
    to_skill_metadata_dto,
)
from autospider.contexts.experience.application.use_cases._result_support import (
    require_trace_id,
)
from autospider.contexts.experience.domain.ports import SkillRepository
from autospider.platform.shared_kernel.result import ResultEnvelope


class LookupSkill:
    def __init__(self, repository: SkillRepository) -> None:
        self._repository = repository

    async def run(self, command: LookupSkillInput) -> ResultEnvelope[LookupSkillResultDTO]:
        trace_id = require_trace_id()
        matches = self._repository.list_by_url(command.url)
        data = LookupSkillResultDTO(matches=[to_skill_metadata_dto(item) for item in matches])
        return ResultEnvelope.success(data=data, trace_id=trace_id)
