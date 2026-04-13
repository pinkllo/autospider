"""Pipeline run persistence helpers."""

from __future__ import annotations

from typing import Any

from .types import PipelineMode, TaskIdentity
from ..domain.fields import FieldDefinition


def _release_inflight_items_for_resume(execution_id: str) -> int:
    if not execution_id:
        return 0
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).release_inflight_items_for_resume(execution_id)


def _persist_run_snapshot(
    *,
    identity: TaskIdentity,
    fields: list[FieldDefinition],
    execution_id: str,
    thread_id: str,
    output_dir: str,
    pipeline_mode: PipelineMode,
    summary: dict[str, Any],
    collection_config: dict[str, Any] | None = None,
    extraction_config: dict[str, Any] | None = None,
    plan_knowledge: str = "",
    task_plan: dict[str, Any] | None = None,
    plan_journal: list[dict[str, Any]] | None = None,
    validation_failures: list[dict[str, Any]] | None = None,
    committed_records: list[dict[str, Any]] | None = None,
) -> None:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository, TaskRunPayload
    from ..common.storage.task_run_query_service import normalize_url

    payload = TaskRunPayload(
        normalized_url=normalize_url(str(identity.list_url or "").strip()),
        original_url=str(identity.list_url or "").strip(),
        page_state_signature=str(identity.page_state_signature or "").strip(),
        anchor_url=str(identity.anchor_url or "").strip(),
        variant_label=str(identity.variant_label or "").strip(),
        task_description=str(identity.task_description or "").strip(),
        field_names=[str(field.name or "").strip() for field in fields if str(field.name or "").strip()],
        execution_id=execution_id,
        thread_id=thread_id,
        output_dir=output_dir,
        pipeline_mode=pipeline_mode.value,
        execution_state=str(summary.get("execution_state") or "running"),
        outcome_state=str(summary.get("outcome_state") or ""),
        promotion_state=str(summary.get("promotion_state") or ""),
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        failed_count=int(summary.get("failed_count", 0) or 0),
        validation_failure_count=int(summary.get("validation_failure_count", 0) or 0),
        success_rate=float(summary.get("success_rate", 0.0) or 0.0),
        error_message=str(summary.get("error") or ""),
        summary_json=dict(summary or {}),
        collection_config=dict(collection_config or {}),
        extraction_config=dict(extraction_config or {}),
        plan_knowledge=str(plan_knowledge or ""),
        task_plan=dict(task_plan or {}),
        plan_journal=list(plan_journal or []),
        validation_failures=list(validation_failures or []),
        committed_records=list(committed_records or []),
    )
    with session_scope() as session:
        TaskRepository(session).save_run(payload)


def _claim_persisted_item(*, execution_id: str, url: str, worker_id: str) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).claim_item(
            execution_id=execution_id,
            url=url,
            worker_id=worker_id,
            item_data={"url": url},
        )


def _commit_persisted_item(
    *,
    execution_id: str,
    url: str,
    item: dict[str, Any],
    worker_id: str,
) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).commit_item(
            execution_id=execution_id,
            url=url,
            item_data=item,
            worker_id=worker_id,
            terminal_reason="success",
        )


def _fail_persisted_item(
    *,
    execution_id: str,
    url: str,
    failure_reason: str,
    item: dict[str, Any],
    worker_id: str,
    terminal_reason: str,
    error_kind: str,
) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).fail_item(
            execution_id=execution_id,
            url=url,
            failure_reason=failure_reason,
            item_data=item,
            worker_id=worker_id,
            terminal_reason=terminal_reason,
            error_kind=error_kind,
        )


def _ack_persisted_item(*, execution_id: str, url: str) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).ack_item(execution_id=execution_id, url=url)


def _release_persisted_claim(
    *,
    execution_id: str,
    url: str,
    worker_id: str,
    terminal_reason: str,
) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).release_claimed_item(
            execution_id=execution_id,
            url=url,
            worker_id=worker_id,
            terminal_reason=terminal_reason,
        )
