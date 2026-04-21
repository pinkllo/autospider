from __future__ import annotations

from typing import Any

from autospider.platform.persistence.sql.orm.engine import session_scope
from autospider.platform.persistence.sql.orm.repositories import TaskRunWriteRepository


class PageResultRepository:
    def claim(self, *, execution_id: str, url: str, worker_id: str) -> dict[str, Any]:
        with session_scope() as session:
            return TaskRunWriteRepository(session).claim_item(
                execution_id=execution_id,
                url=url,
                worker_id=worker_id,
                item_data={"url": url},
            )

    def commit(
        self,
        *,
        execution_id: str,
        url: str,
        item: dict[str, Any],
        worker_id: str,
    ) -> dict[str, Any]:
        with session_scope() as session:
            return TaskRunWriteRepository(session).commit_item(
                execution_id=execution_id,
                url=url,
                item_data=item,
                worker_id=worker_id,
            )

    def fail(
        self,
        *,
        execution_id: str,
        url: str,
        failure_reason: str,
        item: dict[str, Any],
        worker_id: str,
        terminal_reason: str,
        error_kind: str,
    ) -> dict[str, Any]:
        with session_scope() as session:
            return TaskRunWriteRepository(session).fail_item(
                execution_id=execution_id,
                url=url,
                failure_reason=failure_reason,
                item_data=item,
                worker_id=worker_id,
                terminal_reason=terminal_reason,
                error_kind=error_kind,
            )

    def ack(self, *, execution_id: str, url: str) -> dict[str, Any]:
        with session_scope() as session:
            return TaskRunWriteRepository(session).ack_item(execution_id=execution_id, url=url)


__all__ = ["PageResultRepository"]
