"""Read-side SQL repository for task runs."""

from __future__ import annotations

from sqlalchemy.orm import selectinload

from autospider.platform.persistence.sql.orm.models import TaskRecord, TaskRun

from .task_run_support import (
    DURABLE_STATE,
    ELIGIBLE_AGGREGATION_CLAIM_STATES,
    TaskRunRepositorySupport,
)


class TaskRunReadRepository(TaskRunRepositorySupport):
    """Queries and serializers for persisted task runs."""

    def find_by_url(self, normalized_url: str) -> list[dict[str, object]]:
        if not normalized_url:
            return []
        records = self._query_tasks_by_url(normalized_url)
        return self._build_registry_rows(records)

    def list_runs(self, task_id: int, limit: int = 20) -> list[dict[str, object]]:
        records = (
            self._session.query(TaskRun)
            .filter(TaskRun.task_id == task_id)
            .order_by(TaskRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [record.to_dict() for record in records]

    def get_run_detail(self, execution_id: str) -> dict[str, object] | None:
        record = self._query_run_by_execution_id(execution_id)
        return None if record is None else self._serialize_run_detail(record)

    def list_run_items(self, execution_id: str) -> list[dict[str, object]]:
        record = self._query_run_by_execution_id(execution_id)
        return [] if record is None else self._serialize_run_items(record)

    def list_items_by_execution(self, execution_id: str) -> list[dict[str, object]]:
        return self.list_run_items(execution_id)

    def list_eligible_items_by_execution(self, execution_id: str) -> list[dict[str, object]]:
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        items: list[dict[str, object]] = []
        for item in list(record.items or []):
            if not bool(item.success):
                continue
            if str(item.durability_state or "").strip().lower() != DURABLE_STATE:
                continue
            if str(item.claim_state or "").strip().lower() not in ELIGIBLE_AGGREGATION_CLAIM_STATES:
                continue
            items.append(self._serialize_run_item(item))
        return items

    def list_validation_failures(self, execution_id: str) -> list[dict[str, object]]:
        record = self._query_run_by_execution_id(execution_id)
        return [] if record is None else self._serialize_validation_failures(record)

    def list_all_tasks(self, limit: int = 100) -> list[dict[str, object]]:
        records = (
            self._session.query(TaskRecord)
            .options(selectinload(TaskRecord.runs))
            .order_by(TaskRecord.updated_at.desc())
            .limit(limit)
            .all()
        )
        return self._build_registry_rows(records)

    def get_item(self, execution_id: str, url: str) -> dict[str, object] | None:
        item = self._query_run_item(execution_id=execution_id, url=url)
        return None if item is None else self._serialize_run_item(item)


__all__ = ["TaskRunReadRepository"]
