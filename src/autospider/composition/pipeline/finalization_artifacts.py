"""Pipeline artifact and record IO helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autospider.platform.persistence.files.idempotent_io import write_json_idempotent, write_text_if_changed

from .finalization_status import DURABILITY_STATE_DURABLE, DURABILITY_STATE_STAGED

if TYPE_CHECKING:
    from autospider.contexts.collection.domain.fields import FieldDefinition


def build_execution_id(
    *,
    list_url: str,
    task_description: str,
    execution_brief: dict[str, Any] | None = None,
    fields: list["FieldDefinition"],
    target_url_count: int | None,
    max_pages: int | None,
    pipeline_mode: str | None,
    thread_id: str,
    page_state_signature: str = "",
    anchor_url: str | None = None,
    variant_label: str | None = None,
) -> str:
    payload = {
        "list_url": list_url,
        "anchor_url": anchor_url,
        "page_state_signature": page_state_signature,
        "variant_label": variant_label,
        "task_description": task_description,
        "execution_brief": dict(execution_brief or {}),
        "fields": [field.model_dump(mode="python") for field in fields],
        "target_url_count": target_url_count,
        "max_pages": max_pages,
        "pipeline_mode": pipeline_mode,
        "thread_id": thread_id,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def prepare_pipeline_output(
    *,
    output_path: Path,
    items_path: Path,
    summary_path: Path,
) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    items_path.unlink(missing_ok=True)
    summary_path.unlink(missing_ok=True)


def build_run_record(
    *,
    url: str,
    item: dict,
    success: bool,
    failure_reason: str,
    terminal_reason: str = "",
    durability_state: str = DURABILITY_STATE_STAGED,
    record_source: str = "runtime",
    claim_state: str = "pending",
) -> dict:
    return {
        "url": url,
        "success": bool(success),
        "failure_reason": str(failure_reason or ""),
        "terminal_reason": str(terminal_reason or failure_reason or ""),
        "item": dict(item),
        "durability_state": str(durability_state or DURABILITY_STATE_STAGED),
        "durably_persisted": str(durability_state or DURABILITY_STATE_STAGED)
        == DURABILITY_STATE_DURABLE,
        "record_source": str(record_source or "runtime"),
        "claim_state": str(claim_state or "pending"),
    }


def load_persisted_run_records(execution_id: str) -> dict[str, dict]:
    if not execution_id:
        return {}

    from autospider.platform.persistence.sql.orm.engine import session_scope
    from autospider.platform.persistence.sql.orm.repositories import TaskRunReadRepository

    records: dict[str, dict] = {}
    with session_scope() as session:
        persisted_items = TaskRunReadRepository(session).list_run_items(execution_id)
    for item in persisted_items:
        url = str(item.get("url") or "").strip()
        payload = item.get("item")
        if not url or not isinstance(payload, dict):
            continue
        records[url] = build_run_record(
            url=url,
            item=payload,
            success=bool(item.get("success", False)),
            failure_reason=str(item.get("failure_reason") or ""),
            terminal_reason=str(item.get("terminal_reason") or item.get("failure_reason") or ""),
            durability_state=str(item.get("durability_state") or DURABILITY_STATE_DURABLE),
            record_source="db",
            claim_state=str(
                item.get("claim_state")
                or ("committed" if bool(item.get("success", False)) else "failed")
            ),
        )
    return records


def build_record_summary(records: dict[str, dict]) -> dict[str, int]:
    total_urls = len(records)
    success_count = sum(1 for record in records.values() if bool(record.get("success")))
    failed_count = max(total_urls - success_count, 0)
    return {
        "total_urls": total_urls,
        "success_count": success_count,
        "failed_count": failed_count,
    }


def is_durable_record(record: dict[str, Any]) -> bool:
    return str(record.get("durability_state") or "").strip().lower() == DURABILITY_STATE_DURABLE


def normalize_record_summary(summary: dict[str, Any]) -> dict[str, int]:
    total_urls = int(summary.get("total_urls", 0) or 0)
    success_count = int(summary.get("success_count", 0) or 0)
    failed_count = int(summary.get("failed_count", max(total_urls - success_count, 0)) or 0)
    return {
        "total_urls": total_urls,
        "success_count": success_count,
        "failed_count": max(failed_count, 0),
    }


def commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    payload_lines = [
        json.dumps(record["item"], ensure_ascii=False)
        for _, record in sorted(records.items(), key=lambda pair: pair[0])
        if bool(record.get("success")) and is_durable_record(record)
    ]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    write_text_if_changed(items_path, payload)


async def finalize_task_from_record(task: Any, record: dict) -> None:
    if bool(record.get("success")) and str(record.get("durability_state") or "") == DURABILITY_STATE_DURABLE:
        await task.ack_task()
        return
    if bool(record.get("success")):
        await task.fail_task("result_not_durable")
        return
    reason = str(record.get("failure_reason") or "extraction_failed")
    await task.fail_task(reason)


def write_summary(path: Path, summary: dict) -> None:
    write_json_idempotent(
        path,
        summary,
        identity_keys=("run_id", "page_state_signature", "list_url", "task_description"),
        volatile_keys={"created_at", "updated_at", "timestamp", "last_updated"},
    )


def promote_staged_output(staging_path: Path, final_path: Path) -> None:
    staging_path.replace(final_path)
