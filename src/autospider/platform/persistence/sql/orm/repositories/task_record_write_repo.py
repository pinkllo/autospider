"""Task identity upsert helpers for snapshot writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from autospider.platform.persistence.sql.orm.models import TaskRecord

from .task_run_support import (
    TaskRunRepositorySupport,
    _build_registry_id,
    _normalize_run_semantics,
    _require_semantic_signature_for_new_task,
    _resolve_registry_identity,
)


class TaskRecordWriteRepository(TaskRunRepositorySupport):
    """Handles task identity reconciliation and task row upserts."""

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


__all__ = ["TaskRecordWriteRepository"]
