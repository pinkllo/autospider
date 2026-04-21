from __future__ import annotations

from typing import Any

from autospider.platform.persistence.sql.orm.engine import session_scope
from autospider.platform.persistence.sql.orm.repositories import (
    TaskRunPayload,
    TaskRunReadRepository,
    TaskRunWriteRepository,
)


class RunRepository:
    def save(self, payload: TaskRunPayload) -> dict[str, Any]:
        with session_scope() as session:
            return TaskRunWriteRepository(session).save_run(payload).to_dict()

    def load(self, execution_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            return TaskRunReadRepository(session).get_run_detail(execution_id)

    def list_items(self, execution_id: str) -> list[dict[str, Any]]:
        with session_scope() as session:
            return TaskRunReadRepository(session).list_run_items(execution_id)


__all__ = ["RunRepository", "TaskRunPayload"]
