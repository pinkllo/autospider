"""Shared helpers for task run SQL repositories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, selectinload

from autospider.platform.persistence.sql.orm.models import (
    TaskRecord,
    TaskRun,
    TaskRunItem,
)
from autospider.platform.shared_kernel.grouping_semantics import (
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


class TaskRunRepositorySupport:
    """Common SQL helpers shared by read/write repositories."""

    def __init__(self, session: Session):
        self._session = session

    def find_by_execution_id(self, execution_id: str) -> TaskRun | None:
        if not execution_id:
            return None
        return self._session.query(TaskRun).filter(TaskRun.execution_id == execution_id).first()

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


__all__ = [
    "DURABLE_STATE",
    "ELIGIBLE_AGGREGATION_CLAIM_STATES",
    "FINAL_CLAIM_STATES",
    "STAGED_STATE",
    "TaskRunPayload",
    "TaskRunRepositorySupport",
    "_build_auto_execution_id",
    "_build_registry_id",
    "_normalize_run_semantics",
    "_require_semantic_signature_for_new_task",
    "_resolve_registry_identity",
]
