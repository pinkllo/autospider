"""Convert SubTaskRuntimeState ↔ TaskResult."""

from __future__ import annotations

import uuid
from typing import Any

from ..domain.runtime import SubTaskRuntimeState
from ..taskplane.protocol import ResultStatus, TaskResult

_STATUS_MAP: dict[str, ResultStatus] = {
    "completed": ResultStatus.SUCCESS,
    "success": ResultStatus.SUCCESS,
    "expanded": ResultStatus.EXPANDED,
    "system_failure": ResultStatus.FAILED,
    "business_failure": ResultStatus.FAILED,
    "no_data": ResultStatus.FAILED,
}


def _spawned_ticket_from_subtask(raw_subtask: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(raw_subtask.get("id") or "").strip()
    if not ticket_id:
        raise ValueError("spawned_subtask_missing_id")
    labels = {
        "mode": str(raw_subtask.get("mode") or "collect"),
        "depth": str(raw_subtask.get("depth") or 0),
    }
    scope = dict(raw_subtask.get("scope") or {})
    scope_key = str(scope.get("key") or "").strip()
    if scope_key:
        labels["scope_key"] = scope_key
    return {
        "ticket_id": ticket_id,
        "priority": int(raw_subtask.get("priority") or 0),
        "payload": dict(raw_subtask),
        "labels": labels,
    }


def _spawned_tickets(expand_request: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not expand_request:
        return []
    raw_subtasks = list(expand_request.get("spawned_subtasks") or [])
    return [_spawned_ticket_from_subtask(dict(item or {})) for item in raw_subtasks]


class ResultBridge:
    @staticmethod
    def to_result(state: SubTaskRuntimeState) -> TaskResult:
        outcome = str(state.outcome_type or state.status or "").strip().lower()
        artifacts: list[dict[str, str]] = []
        if state.result_file:
            artifacts.append({"label": "result_file", "path": state.result_file})
        return TaskResult(
            result_id=str(uuid.uuid4()),
            ticket_id=state.subtask_id,
            status=_STATUS_MAP.get(outcome, ResultStatus.FAILED),
            output=state.model_dump(mode="python"),
            error=state.error or "",
            artifacts=artifacts,
            spawned_tickets=_spawned_tickets(state.expand_request),
        )

    @staticmethod
    def from_result(result: TaskResult) -> SubTaskRuntimeState:
        return SubTaskRuntimeState.model_validate(result.output)
