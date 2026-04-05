"""Task run query service."""

from __future__ import annotations

from typing import Any

from ..common.db.engine import session_scope
from ..common.db.repositories import TaskRepository
from ..common.storage.task_registry import TaskRegistry


class TaskRunQueryService:
    """面向现版本 PostgreSQL 的运行结果查询服务。"""

    def list_reusable_tasks(self, *, list_url: str) -> list[dict[str, Any]]:
        registry = TaskRegistry()
        return registry.find_by_url(list_url)

    def get_run_detail(self, *, execution_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.get_run_detail(execution_id)

    def list_run_items(self, *, execution_id: str) -> list[dict[str, Any]]:
        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.list_run_items(execution_id)

    def list_validation_failures(self, *, execution_id: str) -> list[dict[str, Any]]:
        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.list_validation_failures(execution_id)
