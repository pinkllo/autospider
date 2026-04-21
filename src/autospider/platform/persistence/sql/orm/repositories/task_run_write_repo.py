"""Write-side SQL repository for task run item state changes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autospider.platform.persistence.sql.orm.models import TaskRun, TaskRunItem

from .task_run_snapshot_write_repo import TaskRunSnapshotWriteRepository
from .task_run_support import DURABLE_STATE, FINAL_CLAIM_STATES, STAGED_STATE


class TaskRunWriteRepository(TaskRunSnapshotWriteRepository):
    """Mutations for claim/commit/ack state transitions."""

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
        if str(row.worker_id or "") != str(worker_id or ""):
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


__all__ = ["TaskRunWriteRepository"]
