"""现版本任务持久化仓储。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from autospider.legacy.common.db.models import (
    TaskRecord,
    TaskRun,
    TaskRunItem,
    TaskRunValidationFailure,
)
from autospider.legacy.common.grouping_semantics import (
    build_normalized_strategy_payload,
    build_semantic_signature_from_payload,
    has_semantic_signature_inputs,
)


FINAL_CLAIM_STATES = {"acked", "failed"}
DURABLE_STATE = "durable"
STAGED_STATE = "staged"
ELIGIBLE_AGGREGATION_CLAIM_STATES = {"committed", "acked"}


def _build_registry_id(
    normalized_url: str,
    semantic_signature: str,
    page_state_signature: str = "",
) -> str:
    raw = f"{normalized_url}:{page_state_signature}:{semantic_signature}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_auto_execution_id(now: datetime) -> str:
    return f"auto_{now.strftime('%Y%m%d_%H%M%S_%f')}"


def _resolve_registry_identity(semantic_signature: str, task_description: str) -> str:
    return str(semantic_signature or task_description or "").strip()


def _normalize_run_semantics(
    *,
    semantic_signature: str,
    strategy_payload: dict[str, Any],
    field_names: list[str],
) -> tuple[str, dict[str, Any], list[str]]:
    normalized_strategy = build_normalized_strategy_payload(
        strategy_payload,
        fallback_field_names=field_names,
    )
    normalized_fields = list(normalized_strategy["field_names"])
    if has_semantic_signature_inputs(strategy_payload, fallback_field_names=field_names):
        return (
            build_semantic_signature_from_payload(
                strategy_payload,
                fallback_field_names=field_names,
            ),
            normalized_strategy,
            normalized_fields,
        )
    return str(semantic_signature or "").strip(), normalized_strategy, normalized_fields


def _require_semantic_signature_for_new_task(
    *,
    semantic_signature: str,
    existing: TaskRecord | None,
) -> None:
    if semantic_signature or existing is not None:
        return
    raise RuntimeError("missing_semantic_signature")


@dataclass(frozen=True, slots=True)
class TaskRunPayload:
    normalized_url: str
    original_url: str
    page_state_signature: str = ""
    anchor_url: str = ""
    variant_label: str = ""
    task_description: str = ""
    semantic_signature: str = ""
    strategy_payload: dict[str, Any] = field(default_factory=dict)
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
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    site_profile_snapshot: dict[str, Any] = field(default_factory=dict)
    failure_patterns: list[dict[str, Any]] = field(default_factory=list)
    plan_knowledge: str = ""
    task_plan: dict[str, Any] = field(default_factory=dict)
    plan_journal: list[dict[str, Any]] = field(default_factory=list)
    committed_records: list[dict[str, Any]] = field(default_factory=list)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskRepository:
    """任务历史数据库读写入口。"""

    def __init__(self, session: Session):
        self._session = session

    def find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        if not normalized_url:
            return []
        records = self._query_tasks_by_url(normalized_url)
        return self._build_registry_rows(records)

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
            run_id=run.id, failures=payload.validation_failures, now=now
        )
        self._session.flush()
        return run

    def find_by_execution_id(self, execution_id: str) -> TaskRun | None:
        if not execution_id:
            return None
        return self._session.query(TaskRun).filter(TaskRun.execution_id == execution_id).first()

    def list_runs(self, task_id: int, limit: int = 20) -> list[dict[str, Any]]:
        records = (
            self._session.query(TaskRun)
            .filter(TaskRun.task_id == task_id)
            .order_by(TaskRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [record.to_dict() for record in records]

    def get_run_detail(self, execution_id: str) -> dict[str, Any] | None:
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return None
        return self._serialize_run_detail(record)

    def list_run_items(self, execution_id: str) -> list[dict[str, Any]]:
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        return self._serialize_run_items(record)

    def list_items_by_execution(self, execution_id: str) -> list[dict[str, Any]]:
        return self.list_run_items(execution_id)

    def list_eligible_items_by_execution(self, execution_id: str) -> list[dict[str, Any]]:
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        items: list[dict[str, Any]] = []
        for item in list(record.items or []):
            if not bool(item.success):
                continue
            if str(item.durability_state or "").strip().lower() != DURABLE_STATE:
                continue
            if str(item.claim_state or "").strip().lower() not in ELIGIBLE_AGGREGATION_CLAIM_STATES:
                continue
            items.append(self._serialize_run_item(item))
        return items

    def list_validation_failures(self, execution_id: str) -> list[dict[str, Any]]:
        record = self._query_run_by_execution_id(execution_id)
        if record is None:
            return []
        return self._serialize_validation_failures(record)

    def list_all_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        records = (
            self._session.query(TaskRecord)
            .options(selectinload(TaskRecord.runs))
            .order_by(TaskRecord.updated_at.desc())
            .limit(limit)
            .all()
        )
        return self._build_registry_rows(records)

    def get_item(self, execution_id: str, url: str) -> dict[str, Any] | None:
        item = self._query_run_item(execution_id=execution_id, url=url)
        if item is None:
            return None
        return self._serialize_run_item(item)

    def claim_item(
        self,
        *,
        execution_id: str,
        url: str,
        worker_id: str,
        item_data: dict[str, Any] | None = None,
        terminal_reason: str = "claimed_for_processing",
    ) -> dict[str, Any]:
        row = self._require_run_item(execution_id=execution_id, url=url, now=datetime.now())
        if row.claim_state == "claimed" and row.worker_id != worker_id:
            raise RuntimeError("duplicate_inflight_claim")
        if row.claim_state in FINAL_CLAIM_STATES or row.durability_state == DURABLE_STATE:
            return self._serialize_run_item(row)
        row.claim_state = "claimed"
        row.durability_state = STAGED_STATE
        row.terminal_reason = terminal_reason
        row.worker_id = str(worker_id or "")
        row.error_kind = ""
        row.attempt_count = max(int(row.attempt_count or 0), 0) + 1
        row.claimed_at = datetime.now()
        row.item_data = dict(item_data or row.item_data or {"url": url})
        self._session.flush()
        return self._serialize_run_item(row)

    def commit_item(
        self,
        *,
        execution_id: str,
        url: str,
        item_data: dict[str, Any],
        worker_id: str,
        terminal_reason: str = "success",
    ) -> dict[str, Any]:
        now = datetime.now()
        row = self._require_run_item(execution_id=execution_id, url=url, now=now)
        row.success = True
        row.failure_reason = ""
        row.item_data = dict(item_data or {"url": url})
        row.claim_state = "committed"
        row.durability_state = DURABLE_STATE
        row.terminal_reason = terminal_reason
        row.error_kind = ""
        row.worker_id = str(worker_id or row.worker_id or "")
        row.durably_committed_at = now
        self._session.flush()
        return self._serialize_run_item(row)

    def fail_item(
        self,
        *,
        execution_id: str,
        url: str,
        failure_reason: str,
        item_data: dict[str, Any] | None = None,
        worker_id: str = "",
        terminal_reason: str = "",
        error_kind: str = "business_failure",
    ) -> dict[str, Any]:
        now = datetime.now()
        row = self._require_run_item(execution_id=execution_id, url=url, now=now)
        row.success = False
        row.failure_reason = str(failure_reason or "")
        row.item_data = dict(item_data or row.item_data or {"url": url})
        row.claim_state = "failed"
        row.durability_state = DURABLE_STATE
        row.terminal_reason = str(terminal_reason or failure_reason or "")
        row.error_kind = str(error_kind or "")
        row.worker_id = str(worker_id or row.worker_id or "")
        row.durably_committed_at = now
        self._session.flush()
        return self._serialize_run_item(row)

    def ack_item(self, *, execution_id: str, url: str) -> dict[str, Any]:
        now = datetime.now()
        row = self._require_run_item(execution_id=execution_id, url=url, now=now)
        if str(row.durability_state or "").strip().lower() != DURABLE_STATE:
            raise RuntimeError("ack_before_durable")
        row.claim_state = "acked"
        row.acked_at = now
        row.updated_at = now
        self._session.flush()
        return self._serialize_run_item(row)

    def release_claimed_item(
        self,
        *,
        execution_id: str,
        url: str,
        worker_id: str,
        terminal_reason: str,
    ) -> dict[str, Any]:
        row = self._query_run_item(execution_id=execution_id, url=url)
        if row is None:
            raise RuntimeError("missing_claimed_item")
        if str(row.claim_state or "").strip().lower() != "claimed":
            raise RuntimeError("release_requires_claimed_item")
        current_worker_id = str(row.worker_id or "")
        expected_worker_id = str(worker_id or "")
        if current_worker_id != expected_worker_id:
            raise RuntimeError("release_claim_worker_mismatch")
        if str(row.durability_state or "").strip().lower() == DURABLE_STATE:
            raise RuntimeError("release_requires_staged_item")
        row.claim_state = "pending"
        row.durability_state = STAGED_STATE
        row.terminal_reason = str(terminal_reason or "released_claim")
        row.worker_id = ""
        row.updated_at = datetime.now()
        self._session.flush()
        return self._serialize_run_item(row)

    def release_inflight_items_for_resume(self, execution_id: str) -> int:
        if not execution_id:
            return 0
        released = 0
        now = datetime.now()
        rows = (
            self._session.query(TaskRunItem)
            .join(TaskRun, TaskRunItem.task_run_id == TaskRun.id)
            .filter(
                TaskRun.execution_id == execution_id,
                TaskRunItem.claim_state == "claimed",
                TaskRunItem.durability_state != DURABLE_STATE,
            )
            .all()
        )
        for row in rows:
            row.claim_state = "pending"
            row.terminal_reason = "resume_released_inflight_claim"
            row.worker_id = ""
            row.updated_at = now
            released += 1
        if released:
            self._session.flush()
        return released

    def _build_registry_rows(self, records: list[TaskRecord]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_registry_ids: set[str] = set()
        for record in records:
            reusable_run = record.latest_reusable_run
            if reusable_run is None:
                continue
            row = record.to_registry_dict(reusable_run)
            registry_id = str(row.get("registry_id") or "")
            if registry_id in seen_registry_ids:
                continue
            seen_registry_ids.add(registry_id)
            rows.append(row)
        return rows

    def _serialize_run_detail(self, run: TaskRun) -> dict[str, Any]:
        return {
            "task": {
                "registry_id": run.task.registry_id,
                "normalized_url": run.task.normalized_url,
                "original_url": run.task.original_url,
                "page_state_signature": run.task.page_state_signature,
                "anchor_url": run.task.anchor_url,
                "variant_label": run.task.variant_label,
                "task_description": run.task.task_description,
                "semantic_signature": run.task.semantic_signature or "",
                "strategy_payload": dict(run.task.strategy_payload or {}),
                "fields": list(run.task.field_names or []),
                "created_at": run.task.created_at.isoformat() if run.task.created_at else "",
                "updated_at": run.task.updated_at.isoformat() if run.task.updated_at else "",
            },
            "run": {
                **run.to_dict(),
                "summary_json": dict(run.summary_json or {}),
                "collection_config": dict(run.collection_config or {}),
                "extraction_config": dict(run.extraction_config or {}),
                "world_snapshot": dict(run.world_snapshot or {}),
                "site_profile_snapshot": dict(run.site_profile_snapshot or {}),
                "failure_patterns": list(run.failure_patterns or []),
                "plan_knowledge": run.plan_knowledge or "",
                "plan_snapshot": dict(run.plan_snapshot or {}),
                "plan_journal": list(run.plan_journal or []),
            },
            "items": self._serialize_run_items(run),
            "validation_failures": self._serialize_validation_failures(run),
        }

    def _serialize_run_items(self, run: TaskRun) -> list[dict[str, Any]]:
        return [self._serialize_run_item(item) for item in list(run.items or [])]

    def _serialize_run_item(self, item: TaskRunItem) -> dict[str, Any]:
        return {
            "url": item.url,
            "success": item.success,
            "failure_reason": item.failure_reason,
            "terminal_reason": item.terminal_reason,
            "claim_state": item.claim_state,
            "durability_state": item.durability_state,
            "error_kind": item.error_kind,
            "attempt_count": int(item.attempt_count or 0),
            "worker_id": item.worker_id or "",
            "item": dict(item.item_data or {}),
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "claimed_at": item.claimed_at.isoformat() if item.claimed_at else "",
            "durably_committed_at": (
                item.durably_committed_at.isoformat() if item.durably_committed_at else ""
            ),
            "acked_at": item.acked_at.isoformat() if item.acked_at else "",
        }

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

    def _query_run_item(self, *, execution_id: str, url: str) -> TaskRunItem | None:
        if not execution_id or not url:
            return None
        return (
            self._session.query(TaskRunItem)
            .join(TaskRun, TaskRunItem.task_run_id == TaskRun.id)
            .filter(TaskRun.execution_id == execution_id, TaskRunItem.url == url)
            .first()
        )

    def _require_run_item(self, *, execution_id: str, url: str, now: datetime) -> TaskRunItem:
        item = self._query_run_item(execution_id=execution_id, url=url)
        if item is not None:
            return item
        run = self.find_by_execution_id(execution_id)
        if run is None:
            raise RuntimeError(f"missing_task_run:{execution_id}")
        item = TaskRunItem(
            task_run_id=run.id,
            url=url,
            item_data={"url": url},
            claim_state="pending",
            durability_state=STAGED_STATE,
            terminal_reason="",
            error_kind="",
            attempt_count=0,
            worker_id="",
            created_at=now,
            updated_at=now,
        )
        self._session.add(item)
        self._session.flush()
        return item

    def _upsert_task(
        self,
        *,
        normalized_url: str,
        original_url: str,
        page_state_signature: str,
        anchor_url: str,
        variant_label: str,
        task_description: str,
        semantic_signature: str,
        strategy_payload: dict[str, Any],
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        existing = self._find_task(
            normalized_url=normalized_url,
            page_state_signature=page_state_signature,
            semantic_signature=semantic_signature,
            task_description=task_description,
        )
        _require_semantic_signature_for_new_task(
            semantic_signature=semantic_signature,
            existing=existing,
        )
        if existing is not None:
            return self._update_task(
                task=existing,
                original_url=original_url,
                anchor_url=anchor_url,
                variant_label=variant_label,
                task_description=task_description,
                semantic_signature=semantic_signature,
                strategy_payload=strategy_payload,
                field_names=field_names,
                now=now,
            )
        return self._create_task(
            normalized_url=normalized_url,
            original_url=original_url,
            page_state_signature=page_state_signature,
            anchor_url=anchor_url,
            variant_label=variant_label,
            task_description=task_description,
            semantic_signature=semantic_signature,
            strategy_payload=strategy_payload,
            field_names=field_names,
            now=now,
        )

    def _find_task(
        self,
        *,
        normalized_url: str,
        page_state_signature: str,
        semantic_signature: str,
        task_description: str,
    ) -> TaskRecord | None:
        query = self._session.query(TaskRecord).filter(
            TaskRecord.normalized_url == normalized_url,
            TaskRecord.page_state_signature == (page_state_signature or ""),
        )
        if semantic_signature:
            match = query.filter(TaskRecord.semantic_signature == semantic_signature).first()
            if match is not None:
                return match
            legacy_rows = query.filter(
                or_(TaskRecord.semantic_signature.is_(None), TaskRecord.semantic_signature == "")
            ).all()
            for row in legacy_rows:
                legacy_signature, _, _ = _normalize_run_semantics(
                    semantic_signature="",
                    strategy_payload=dict(row.strategy_payload or {}),
                    field_names=list(row.field_names or []),
                )
                if legacy_signature == semantic_signature:
                    return row
            return None
        if not task_description:
            return None
        return query.filter(
            TaskRecord.task_description == task_description,
            or_(TaskRecord.semantic_signature.is_(None), TaskRecord.semantic_signature == ""),
        ).first()

    def _update_task(
        self,
        *,
        task: TaskRecord,
        original_url: str,
        anchor_url: str,
        variant_label: str,
        task_description: str,
        semantic_signature: str,
        strategy_payload: dict[str, Any],
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        registry_identity = _resolve_registry_identity(semantic_signature, task_description)
        task.original_url = original_url
        task.anchor_url = anchor_url or ""
        task.variant_label = variant_label or ""
        task.task_description = task_description or task.task_description
        task.semantic_signature = semantic_signature or task.semantic_signature
        task.registry_id = _build_registry_id(
            task.normalized_url,
            registry_identity,
            task.page_state_signature,
        )
        task.strategy_payload = dict(strategy_payload or task.strategy_payload or {})
        task.field_names = field_names
        task.updated_at = now
        self._session.flush()
        return task

    def _create_task(
        self,
        *,
        normalized_url: str,
        original_url: str,
        page_state_signature: str,
        anchor_url: str,
        variant_label: str,
        task_description: str,
        semantic_signature: str,
        strategy_payload: dict[str, Any],
        field_names: list[str],
        now: datetime,
    ) -> TaskRecord:
        registry_identity = _resolve_registry_identity(semantic_signature, task_description)
        task = TaskRecord(
            registry_id=_build_registry_id(normalized_url, registry_identity, page_state_signature),
            normalized_url=normalized_url,
            original_url=original_url,
            page_state_signature=page_state_signature or "",
            anchor_url=anchor_url or "",
            variant_label=variant_label or "",
            task_description=task_description,
            semantic_signature=semantic_signature or None,
            strategy_payload=dict(strategy_payload or {}),
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
            existing = self._find_task(
                normalized_url=normalized_url,
                page_state_signature=page_state_signature,
                semantic_signature=semantic_signature,
                task_description=task_description,
            )
            if existing is None:
                raise
            return self._update_task(
                task=existing,
                original_url=original_url,
                anchor_url=anchor_url,
                variant_label=variant_label,
                task_description=task_description,
                semantic_signature=semantic_signature,
                strategy_payload=strategy_payload,
                field_names=field_names,
                now=now,
            )

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
                .filter(
                    TaskRunItem.task_run_id == run_id,
                    TaskRunItem.url == url,
                )
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
            row.attempt_count = max(
                int(record.get("attempt_count", row.attempt_count or 1) or 1), 1
            )
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
