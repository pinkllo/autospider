"""现版本任务持久化仓储。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from autospider.common.db.models import (
    TaskRecord,
    TaskRun,
    TaskRunItem,
    TaskRunValidationFailure,
)


def _build_registry_id(normalized_url: str, task_description: str) -> str:
    raw = f"{normalized_url}:{task_description}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_auto_execution_id(now: datetime) -> str:
    return f"auto_{now.strftime('%Y%m%d_%H%M%S_%f')}"


@dataclass(frozen=True, slots=True)
class TaskRunPayload:
    normalized_url: str
    original_url: str
    task_description: str
    field_names: list[str] = field(default_factory=list)
    execution_id: str = ""
    thread_id: str = ""
    output_dir: str = ""
    pipeline_mode: str = ""
    execution_state: str = "running"
    outcome_state: str = ""
    promotion_state: str = ""
    total_urls: int = 0
    success_count: int = 0
    failed_count: int = 0
    validation_failure_count: int = 0
    success_rate: float = 0.0
    error_message: str = ""
    summary_json: dict[str, Any] = field(default_factory=dict)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    plan_knowledge: str = ""
    committed_records: list[dict[str, Any]] = field(default_factory=list)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskRepository:
    """任务历史数据库读写入口。"""

    def __init__(self, session: Session):
        self._session = session

    def find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        """按归一化 URL 查询可复用历史任务。"""
        if not normalized_url:
            return []
        records = self._query_tasks_by_url(normalized_url)
        return self._build_registry_rows(records)

    def save_run(self, payload: TaskRunPayload) -> TaskRun:
        """保存单次运行快照及其明细。"""
        now = datetime.now()
        task = self._upsert_task(
            normalized_url=payload.normalized_url,
            original_url=payload.original_url,
            task_description=payload.task_description,
            field_names=list(payload.field_names),
            now=now,
        )
        execution_id = payload.execution_id or _build_auto_execution_id(now)
        run = self.find_by_execution_id(execution_id)
        if run is None:
            run = self._create_run(task=task, execution_id=execution_id, payload=payload, now=now)
        else:
            self._update_run(run=run, task=task, payload=payload, now=now)
        self._replace_run_items(run_id=run.id, records=payload.committed_records, now=now)
        self._replace_validation_failures(
            run_id=run.id,
            failures=payload.validation_failures,
            now=now,
        )
        self._session.flush()
        return run

    def find_by_execution_id(self, execution_id: str) -> TaskRun | None:
        """按 execution_id 查找运行记录。"""
        if not execution_id:
            return None
        return self._session.query(TaskRun).filter(TaskRun.execution_id == execution_id).first()

    def list_runs(self, task_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """列出某个任务的运行历史。"""
        records = (
            self._session.query(TaskRun)
            .filter(TaskRun.task_id == task_id)
            .order_by(TaskRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [record.to_dict() for record in records]

    def get_run_detail(self, execution_id: str) -> dict[str, Any] | None:
        """读取单次运行的完整详情。"""
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return None
        return self._serialize_run_detail(record)

    def list_run_items(self, execution_id: str) -> list[dict[str, Any]]:
        """列出某次运行的结果明细。"""
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        return self._serialize_run_items(record)

    def list_validation_failures(self, execution_id: str) -> list[dict[str, Any]]:
        """列出某次运行的校验失败明细。"""
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        return self._serialize_validation_failures(record)

    def list_all_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出最近更新的任务定义。"""
        records = (
            self._session.query(TaskRecord)
            .options(selectinload(TaskRecord.runs))
            .order_by(TaskRecord.updated_at.desc())
            .limit(limit)
            .all()
        )
        return self._build_registry_rows(records)

    def _build_registry_rows(self, records: list[TaskRecord]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in records:
            reusable_run = record.latest_reusable_run
            if reusable_run is None:
                continue
            rows.append(record.to_registry_dict(reusable_run))
        return rows

    def _serialize_run_detail(self, run: TaskRun) -> dict[str, Any]:
        return {
            "task": {
                "registry_id": run.task.registry_id,
                "normalized_url": run.task.normalized_url,
                "original_url": run.task.original_url,
                "task_description": run.task.task_description,
                "fields": list(run.task.field_names or []),
                "created_at": run.task.created_at.isoformat() if run.task.created_at else "",
                "updated_at": run.task.updated_at.isoformat() if run.task.updated_at else "",
            },
            "run": {
                **run.to_dict(),
                "summary_json": dict(run.summary_json or {}),
                "collection_config": dict(run.collection_config or {}),
                "extraction_config": dict(run.extraction_config or {}),
                "plan_knowledge": run.plan_knowledge or "",
            },
            "items": self._serialize_run_items(run),
            "validation_failures": self._serialize_validation_failures(run),
        }

    def _serialize_run_items(self, run: TaskRun) -> list[dict[str, Any]]:
        return [
            {
                "url": item.url,
                "success": item.success,
                "failure_reason": item.failure_reason,
                "item": dict(item.item_data or {}),
                "created_at": item.created_at.isoformat() if item.created_at else "",
            }
            for item in list(run.items or [])
        ]

    def _serialize_validation_failures(self, run: TaskRun) -> list[dict[str, Any]]:
        return [dict(item.failure_data or {}) for item in list(run.validation_failures or [])]

    def _query_tasks_by_url(self, normalized_url: str) -> list[TaskRecord]:
        return (
            self._session.query(TaskRecord)
            .options(selectinload(TaskRecord.runs))
            .filter(TaskRecord.normalized_url == normalized_url)
            .order_by(TaskRecord.updated_at.desc())
            .all()
        )

    def _query_run_by_execution_id(self, execution_id: str) -> TaskRun | None:
        if not execution_id:
            return None
        return (
            self._session.query(TaskRun)
            .options(
                selectinload(TaskRun.task),
                selectinload(TaskRun.items),
                selectinload(TaskRun.validation_failures),
            )
            .filter(TaskRun.execution_id == execution_id)
            .first()
        )

    def _upsert_task(
        self,
        *,
        normalized_url: str,
        original_url: str,
        task_description: str,
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        existing = self._find_task(normalized_url, task_description)
        if existing is not None:
            return self._update_task(existing, original_url, field_names, now)
        return self._create_task(normalized_url, original_url, task_description, field_names, now)

    def _find_task(self, normalized_url: str, task_description: str) -> TaskRecord | None:
        return (
            self._session.query(TaskRecord)
            .filter(
                TaskRecord.normalized_url == normalized_url,
                TaskRecord.task_description == task_description,
            )
            .first()
        )

    def _update_task(
        self,
        task: TaskRecord,
        original_url: str,
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        task.original_url = original_url
        task.field_names = field_names
        task.updated_at = now
        self._session.flush()
        return task

    def _create_task(
        self,
        normalized_url: str,
        original_url: str,
        task_description: str,
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        task = TaskRecord(
            registry_id=_build_registry_id(normalized_url, task_description),
            normalized_url=normalized_url,
            original_url=original_url,
            task_description=task_description,
            field_names=field_names,
            created_at=now,
            updated_at=now,
        )
        savepoint = self._session.begin_nested()
        try:
            self._session.add(task)
            self._session.flush()
            savepoint.commit()
            return task
        except IntegrityError:
            savepoint.rollback()
            existing = self._find_task(normalized_url, task_description)
            if existing is None:
                raise
            return self._update_task(existing, original_url, field_names, now)

    def _create_run(
        self,
        *,
        task: TaskRecord,
        execution_id: str,
        payload: TaskRunPayload,
        now: datetime,
    ) -> TaskRun:
        run = TaskRun(
            task_id=task.id,
            execution_id=execution_id,
            thread_id=payload.thread_id,
            output_dir=payload.output_dir,
            pipeline_mode=payload.pipeline_mode,
            execution_state=payload.execution_state,
            outcome_state=payload.outcome_state,
            promotion_state=payload.promotion_state,
            total_urls=payload.total_urls,
            success_count=payload.success_count,
            failed_count=payload.failed_count,
            validation_failure_count=payload.validation_failure_count,
            success_rate=payload.success_rate,
            error_message=payload.error_message,
            summary_json=dict(payload.summary_json),
            collection_config=dict(payload.collection_config),
            extraction_config=dict(payload.extraction_config),
            plan_knowledge=payload.plan_knowledge,
            started_at=payload.started_at or now,
            completed_at=self._resolve_completed_at(payload=payload, now=now),
            created_at=now,
            updated_at=now,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def _update_run(
        self,
        *,
        run: TaskRun,
        task: TaskRecord,
        payload: TaskRunPayload,
        now: datetime,
    ) -> None:
        run.task_id = task.id
        run.thread_id = payload.thread_id or run.thread_id
        run.output_dir = payload.output_dir or run.output_dir
        run.pipeline_mode = payload.pipeline_mode or run.pipeline_mode
        run.execution_state = payload.execution_state or run.execution_state
        run.outcome_state = payload.outcome_state or run.outcome_state
        run.promotion_state = payload.promotion_state or run.promotion_state
        run.total_urls = payload.total_urls
        run.success_count = payload.success_count
        run.failed_count = payload.failed_count
        run.validation_failure_count = payload.validation_failure_count
        run.success_rate = payload.success_rate
        run.error_message = payload.error_message
        run.summary_json = dict(payload.summary_json)
        run.collection_config = dict(payload.collection_config)
        run.extraction_config = dict(payload.extraction_config)
        run.plan_knowledge = payload.plan_knowledge
        if payload.started_at:
            run.started_at = payload.started_at
        run.completed_at = self._resolve_completed_at(payload=payload, now=now)
        run.updated_at = now
        self._session.flush()

    def _resolve_completed_at(self, *, payload: TaskRunPayload, now: datetime) -> datetime | None:
        if payload.completed_at is not None:
            return payload.completed_at
        if payload.execution_state in {"completed", "failed"}:
            return now
        return None

    def _replace_run_items(
        self,
        *,
        run_id: int,
        records: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        self._session.query(TaskRunItem).filter(TaskRunItem.task_run_id == run_id).delete()
        for record in records:
            url = str(record.get("url") or "").strip()
            if not url:
                continue
            self._session.add(
                TaskRunItem(
                    task_run_id=run_id,
                    url=url,
                    success=bool(record.get("success", False)),
                    failure_reason=str(record.get("failure_reason") or ""),
                    item_data=dict(record.get("item") or {}),
                    created_at=now,
                )
            )

    def _replace_validation_failures(
        self,
        *,
        run_id: int,
        failures: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        self._session.query(TaskRunValidationFailure).filter(
            TaskRunValidationFailure.task_run_id == run_id
        ).delete()
        for failure in failures:
            self._session.add(
                TaskRunValidationFailure(
                    task_run_id=run_id,
                    url=str(failure.get("url") or ""),
                    failure_data=dict(failure),
                    created_at=now,
                )
            )
