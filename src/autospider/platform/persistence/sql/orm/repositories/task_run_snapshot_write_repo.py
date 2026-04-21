"""Snapshot persistence for task/task-run SQL writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autospider.platform.persistence.sql.orm.models import (
    TaskRun,
    TaskRunItem,
    TaskRunValidationFailure,
)

from .task_record_write_repo import TaskRecordWriteRepository
from .task_run_support import (
    DURABLE_STATE,
    TaskRunPayload,
    _build_auto_execution_id,
    _normalize_run_semantics,
)


class TaskRunSnapshotWriteRepository(TaskRecordWriteRepository):
    """Writes task/run snapshots and their durable record copies."""

    def save_run(self, payload: TaskRunPayload) -> TaskRun:
        now = datetime.now()
        semantic_signature, strategy_payload, field_names = _normalize_run_semantics(
            semantic_signature=payload.semantic_signature,
            strategy_payload=dict(payload.strategy_payload),
            field_names=list(payload.field_names),
        )
        task = self._upsert_task(
            normalized_url=payload.normalized_url,
            original_url=payload.original_url,
            page_state_signature=payload.page_state_signature,
            anchor_url=payload.anchor_url,
            variant_label=payload.variant_label,
            task_description=payload.task_description,
            semantic_signature=semantic_signature,
            strategy_payload=strategy_payload,
            field_names=field_names,
            now=now,
        )
        execution_id = payload.execution_id or _build_auto_execution_id(now)
        run = self.find_by_execution_id(execution_id)
        if run is None:
            run = self._create_run(task=task, execution_id=execution_id, payload=payload, now=now)
        else:
            self._update_run(run=run, task=task, payload=payload, now=now)
        self._upsert_committed_records(run_id=run.id, records=payload.committed_records, now=now)
        self._replace_validation_failures(
            run_id=run.id,
            failures=payload.validation_failures,
            now=now,
        )
        self._session.flush()
        return run

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
            world_snapshot=dict(payload.world_snapshot),
            site_profile_snapshot=dict(payload.site_profile_snapshot),
            failure_patterns=list(payload.failure_patterns),
            plan_knowledge=payload.plan_knowledge,
            plan_snapshot=dict(payload.task_plan),
            plan_journal=list(payload.plan_journal),
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
        run.world_snapshot = dict(payload.world_snapshot)
        run.site_profile_snapshot = dict(payload.site_profile_snapshot)
        run.failure_patterns = list(payload.failure_patterns)
        run.plan_knowledge = payload.plan_knowledge
        run.plan_snapshot = dict(payload.task_plan)
        run.plan_journal = list(payload.plan_journal)
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

    def _upsert_committed_records(
        self,
        *,
        run_id: int,
        records: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        for record in records:
            url = str(record.get("url") or "").strip()
            if not url:
                continue
            row = (
                self._session.query(TaskRunItem)
                .filter(TaskRunItem.task_run_id == run_id, TaskRunItem.url == url)
                .first()
            )
            if row is None:
                row = TaskRunItem(task_run_id=run_id, url=url, created_at=now, updated_at=now)
                self._session.add(row)
            row.success = bool(record.get("success", False))
            row.failure_reason = str(record.get("failure_reason") or "")
            row.terminal_reason = str(record.get("terminal_reason") or row.failure_reason or "")
            row.claim_state = str(
                record.get("claim_state") or ("committed" if row.success else "failed")
            )
            row.durability_state = str(record.get("durability_state") or DURABLE_STATE)
            row.error_kind = str(record.get("error_kind") or "")
            row.attempt_count = max(int(record.get("attempt_count", row.attempt_count or 1) or 1), 1)
            row.worker_id = str(record.get("worker_id") or row.worker_id or "")
            row.item_data = dict(record.get("item") or {})
            row.claimed_at = row.claimed_at or now
            if row.durability_state == DURABLE_STATE:
                row.durably_committed_at = row.durably_committed_at or now
            if row.claim_state == "acked":
                row.acked_at = row.acked_at or now
            row.updated_at = now

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


__all__ = ["TaskRunSnapshotWriteRepository"]
