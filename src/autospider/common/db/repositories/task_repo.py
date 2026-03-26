"""任务注册表 Repository — 替代 JSON 文件存储。

提供与原 TaskRegistry 完全兼容的 API 接口，
底层从文件读写切换到 SQLAlchemy + PostgreSQL。

层级关系：
    TaskRecord（任务定义，按 URL+描述 去重）
        → TaskExecution（每次执行记录，永不覆盖）
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from autospider.common.db.models import TaskRecord, TaskExecution
from autospider.common.logger import get_logger

logger = get_logger(__name__)


class TaskRepository:
    """任务注册表数据库 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    # =================================================================
    # TaskRegistry 兼容 API
    # =================================================================

    def find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        """按归一化 URL 查找所有历史任务记录（最近更新的在前）。

        返回格式与旧 JSON 格式兼容（to_dict 会从最新 execution 取状态字段）。
        """
        if not normalized_url:
            return []

        records = (
            self._session.query(TaskRecord)
            .filter(TaskRecord.normalized_url == normalized_url)
            .order_by(TaskRecord.updated_at.desc())
            .all()
        )
        return [r.to_dict() for r in records]

    def register(
        self,
        *,
        normalized_url: str,
        original_url: str,
        task_description: str,
        fields: list[str] | None = None,
        execution_id: str = "",
        output_dir: str = "",
        status: str = "completed",
        collected_count: int = 0,
    ) -> TaskRecord:
        """注册一次任务执行。

        1. 查找或创建 TaskRecord（按 normalized_url + task_description 去重）
        2. 在该 TaskRecord 下创建或更新 TaskExecution（按 execution_id 去重）

        每次执行都保留历史记录，不会覆盖。
        """
        registry_id = hashlib.sha1(
            f"{normalized_url}:{task_description}".encode("utf-8")
        ).hexdigest()[:8]

        now = datetime.now()

        # 1. 查找或创建任务定义
        task = (
            self._session.query(TaskRecord)
            .filter(
                TaskRecord.normalized_url == normalized_url,
                TaskRecord.task_description == task_description,
            )
            .first()
        )

        if task is None:
            task = TaskRecord(
                registry_id=registry_id,
                normalized_url=normalized_url,
                original_url=original_url,
                task_description=task_description,
                fields=list(fields or []),
                created_at=now,
                updated_at=now,
            )
            self._session.add(task)
            self._session.flush()  # 获取 task.id
        else:
            # 更新字段列表和时间戳
            task.fields = list(fields or []) if fields else task.fields
            task.original_url = original_url
            task.updated_at = now

        # 2. 创建或更新执行记录
        execution = None
        if execution_id:
            execution = (
                self._session.query(TaskExecution)
                .filter(TaskExecution.execution_id == execution_id)
                .first()
            )

        if execution is not None:
            # 更新已有执行记录
            execution.status = status
            execution.collected_count = collected_count
            execution.output_dir = output_dir or execution.output_dir
            execution.fields = list(fields or []) if fields else execution.fields
            if status in {"completed", "failed"}:
                execution.completed_at = now
            self._session.flush()
            logger.info(
                "[TaskRepo] 已更新执行: %s -> %s (采集 %d 条)",
                normalized_url,
                task_description[:40],
                collected_count,
            )
        else:
            # 创建新执行记录
            execution = TaskExecution(
                task_id=task.id,
                execution_id=execution_id or f"auto_{now.strftime('%Y%m%d_%H%M%S')}",
                output_dir=output_dir,
                status=status,
                collected_count=collected_count,
                fields=list(fields or []),
                started_at=now,
                completed_at=now if status in {"completed", "failed"} else None,
                created_at=now,
            )
            self._session.add(execution)
            self._session.flush()
            logger.info(
                "[TaskRepo] 已注册执行: %s -> %s (采集 %d 条)",
                normalized_url,
                task_description[:40],
                collected_count,
            )

        return task

    # =================================================================
    # 扩展查询 API
    # =================================================================

    def find_by_execution_id(self, execution_id: str) -> TaskExecution | None:
        """按 execution_id 精确查找执行记录。"""
        if not execution_id:
            return None
        return (
            self._session.query(TaskExecution)
            .filter(TaskExecution.execution_id == execution_id)
            .first()
        )

    def list_executions(self, task_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """列出某个任务的所有执行历史（最近的在前）。"""
        records = (
            self._session.query(TaskExecution)
            .filter(TaskExecution.task_id == task_id)
            .order_by(TaskExecution.started_at.desc())
            .limit(limit)
            .all()
        )
        return [r.to_dict() for r in records]

    def list_all_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出最近的任务定义。"""
        records = (
            self._session.query(TaskRecord)
            .order_by(TaskRecord.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [r.to_dict() for r in records]
