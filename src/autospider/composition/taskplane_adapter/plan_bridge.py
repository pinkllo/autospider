"""Convert TaskPlan ↔ PlanEnvelope."""

from __future__ import annotations

from typing import Any

from autospider.contexts.planning.domain import TaskPlan
from ..taskplane.protocol import PlanEnvelope
from .subtask_bridge import SubtaskBridge


class PlanBridge:
    @staticmethod
    def to_envelope(
        plan: TaskPlan,
        *,
        source_agent: str = "plan_node",
        request_params: dict[str, Any] | None = None,
    ) -> PlanEnvelope:
        tickets = [
            SubtaskBridge.to_ticket(subtask, envelope_id=plan.plan_id) for subtask in plan.subtasks
        ]
        metadata = {
            "original_request": plan.original_request,
            "site_url": plan.site_url,
            "shared_fields": list(plan.shared_fields or []),
        }
        metadata.update(dict(request_params or {}))
        return PlanEnvelope(
            envelope_id=plan.plan_id,
            source_agent=source_agent,
            metadata=metadata,
            tickets=tickets,
            plan_snapshot=plan.model_dump(mode="python"),
        )

    @staticmethod
    def from_envelope(envelope: PlanEnvelope) -> TaskPlan:
        return TaskPlan.model_validate(envelope.plan_snapshot)
