"""Pipeline finalization helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlparse

import yaml

from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed

if TYPE_CHECKING:
    from ..domain.fields import FieldDefinition
    from .orchestration import PipelineSessionBundle
    from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


def _is_valid_xpath(xpath: object) -> bool:
    return isinstance(xpath, str) and xpath.strip().startswith("/")


def prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    valid_fields: list[dict] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for field in fields_config:
        if not isinstance(field, dict):
            continue

        field_name = str(field.get("name") or "").strip() or "<unknown>"
        xpath = field.get("xpath")
        required = bool(field.get("required", True))
        data_type = str(field.get("data_type") or "").strip().lower()
        source = str(field.get("extraction_source") or "").strip().lower()
        fixed_value = field.get("fixed_value")

        if _is_valid_xpath(xpath):
            normalized = dict(field)
            normalized["xpath"] = str(xpath).strip()
            valid_fields.append(normalized)
            continue

        if source in {"constant", "subtask_context"}:
            value = "" if fixed_value is None else str(fixed_value).strip()
            if value:
                normalized = dict(field)
                normalized["xpath"] = None
                normalized["extraction_source"] = source
                normalized["fixed_value"] = value
                valid_fields.append(normalized)
                continue

        if data_type == "url":
            normalized = dict(field)
            normalized["xpath"] = None
            normalized["extraction_source"] = "task_url"
            valid_fields.append(normalized)
            continue

        if required:
            missing_required.append(field_name)
        else:
            missing_optional.append(field_name)

    return valid_fields, missing_required, missing_optional


def find_output_draft_skill(list_url: str, output_dir: str) -> tuple[str, Path] | None:
    domain = urlparse(str(list_url or "")).netloc.strip().lower()
    if not domain:
        return None

    output_path = Path(output_dir)
    candidates = [
        output_path / "draft_skills" / domain / "SKILL.md",
        output_path.parent / "draft_skills" / domain / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return domain, candidate
    return None


def cleanup_output_draft_skill(list_url: str, output_dir: str) -> None:
    located = find_output_draft_skill(list_url, output_dir)
    if located is None:
        return

    _, draft_path = located
    try:
        draft_path.unlink(missing_ok=True)
        logger.info("[Pipeline] 已清理输出目录中的 Draft Skill: %s", draft_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Pipeline] 清理 Draft Skill 失败（不影响主流程）: %s", exc)


def classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
) -> dict[str, object]:
    failed_count = max(total_urls - success_count, 0)
    success_rate = (success_count / total_urls) if total_urls > 0 else 0.0
    validation_failure_count = len(validation_failures)
    execution_state = "failed" if state_error else "completed"

    if success_count <= 0 or total_urls <= 0:
        outcome_state = "failed"
    elif not state_error and success_rate > 0.7 and validation_failure_count == 0:
        outcome_state = "success"
    else:
        outcome_state = "partial_success"

    if (
        total_urls > 0
        and success_count > 0
        and not state_error
        and success_rate > 0.7
        and validation_failure_count == 0
    ):
        promotion_state = "reusable"
    elif success_count > 0:
        promotion_state = "diagnostic_only"
    else:
        promotion_state = "rejected"

    return {
        "execution_state": execution_state,
        "outcome_state": outcome_state,
        "promotion_state": promotion_state,
        "success_rate": round(success_rate, 4),
        "failed_count": failed_count,
        "required_field_success_rate": round(success_rate, 4),
        "validation_failure_count": validation_failure_count,
    }


def should_promote_skill(
    *,
    state: dict[str, object],
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    if str(summary.get("promotion_state") or "").strip().lower() == "reusable":
        return True

    classified = classify_pipeline_result(
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        state_error=state.get("error"),
        validation_failures=validation_failures,
    )
    return bool(classified.get("promotion_state") == "reusable")


def strip_draft_markers_from_skill_content(content: str) -> str:
    text = str(content or "")
    if not text.strip():
        return text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except Exception:
                frontmatter = None
            if isinstance(frontmatter, dict):
                description = str(frontmatter.get("description") or "").strip()
                if description:
                    frontmatter["description"] = (
                        description.replace("（草稿）", "").replace("草稿", "").strip()
                    )
                rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
                text = f"---\n{rendered}\n---{parts[2]}"

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        if line.startswith("# ") and "（草稿）" in line:
            line = line.replace("（草稿）", "")
        if line.startswith("- **状态**:") and ("draft" in line.lower() or "草稿" in line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    if cleaned:
        cleaned += "\n"
    return cleaned


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
    durably_persisted: bool = False,
    record_source: str = "runtime",
) -> dict:
    return {
        "url": url,
        "success": bool(success),
        "failure_reason": str(failure_reason or ""),
        "item": dict(item),
        "durably_persisted": bool(durably_persisted),
        "record_source": str(record_source or "runtime"),
    }


def load_persisted_run_records(execution_id: str) -> dict[str, dict]:
    if not execution_id:
        return {}

    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    records: dict[str, dict] = {}
    with session_scope() as session:
        persisted_items = TaskRepository(session).list_run_items(execution_id)
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
            durably_persisted=True,
            record_source="db",
        )
    return records


def build_record_summary(records: dict[str, dict]) -> dict[str, int]:
    total_urls = len(records)
    success_count = sum(1 for record in records.values() if bool(record.get("success")))
    return {
        "total_urls": total_urls,
        "success_count": success_count,
    }


def commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    payload_lines = [
        json.dumps(record["item"], ensure_ascii=False)
        for _, record in sorted(records.items(), key=lambda pair: pair[0])
    ]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    write_text_if_changed(items_path, payload)


async def finalize_task_from_record(task: Any, record: dict) -> None:
    if bool(record.get("success")) and bool(record.get("durably_persisted")):
        await task.ack_task()
        return
    if bool(record.get("success")):
        await task.fail_task("result_not_persisted")
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


def _coerce_field_names(fields: list["FieldDefinition"]) -> list[str]:
    names: list[str] = []
    for field in fields:
        name = str(getattr(field, "name", "") or "").strip()
        if name:
            names.append(name)
    return names


def persist_pipeline_run(context: "PipelineFinalizationContext", records: dict[str, dict]) -> None:
    """将现版本运行结果持久化到 PostgreSQL。"""
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository, TaskRunPayload
    from ..common.storage.task_registry import invalidate_task_cache, normalize_url

    normalized_url = normalize_url(context.list_url)
    if not normalized_url:
        return

    payload = TaskRunPayload(
        normalized_url=normalized_url,
        original_url=context.list_url,
        page_state_signature=str(context.page_state_signature or ""),
        anchor_url=str(context.anchor_url or ""),
        variant_label=str(context.variant_label or ""),
        task_description=context.task_description,
        field_names=_coerce_field_names(context.fields),
        execution_id=str(context.summary.get("execution_id") or context.summary.get("run_id") or ""),
        thread_id=context.thread_id,
        output_dir=context.output_dir,
        pipeline_mode=str(context.summary.get("mode") or ""),
        execution_state=str(context.summary.get("execution_state") or ""),
        outcome_state=str(context.summary.get("outcome_state") or ""),
        promotion_state=str(context.summary.get("promotion_state") or ""),
        total_urls=int(context.summary.get("total_urls", 0) or 0),
        success_count=int(context.summary.get("success_count", 0) or 0),
        failed_count=int(context.summary.get("failed_count", 0) or 0),
        validation_failure_count=int(context.summary.get("validation_failure_count", 0) or 0),
        success_rate=float(context.summary.get("success_rate", 0.0) or 0.0),
        error_message=str(context.summary.get("error") or ""),
        summary_json=dict(context.summary or {}),
        collection_config=dict(context.collection_config or {}),
        extraction_config=dict(context.extraction_config or {}),
        plan_knowledge=str(context.plan_knowledge or ""),
        task_plan=dict(context.task_plan or {}),
        plan_journal=list(context.plan_journal or []),
        committed_records=list(records.values()),
        validation_failures=list(context.validation_failures or []),
    )
    with session_scope() as session:
        repo = TaskRepository(session)
        repo.save_run(payload)
    invalidate_task_cache(context.list_url)


@dataclass(slots=True)
class PipelineFinalizationContext:
    list_url: str
    anchor_url: str | None
    page_state_signature: str
    variant_label: str | None
    task_description: str
    execution_brief: dict[str, Any]
    fields: list["FieldDefinition"]
    thread_id: str
    output_dir: str
    output_path: Path
    items_path: Path
    summary_path: Path
    committed_records: dict[str, dict[str, Any]]
    summary: dict[str, Any]
    state: dict[str, object]
    collection_config: dict[str, Any]
    extraction_config: dict[str, Any]
    validation_failures: list[dict[str, Any]]
    plan_knowledge: str
    task_plan: dict[str, Any]
    plan_journal: list[dict[str, Any]]
    tracker: "TaskProgressTracker"
    sessions: "PipelineSessionBundle"


@dataclass(frozen=True, slots=True)
class PipelineFinalizationDependencies:
    build_record_summary: Callable[[dict[str, dict]], dict[str, int]]
    classify_pipeline_result: Callable[..., dict[str, object]]
    persist_pipeline_run: Callable[["PipelineFinalizationContext", dict[str, dict]], None]
    commit_items_file: Callable[[Path, dict[str, dict]], None]
    write_summary: Callable[[Path, dict], None]


class PipelineFinalizer:
    def __init__(self, dependencies: PipelineFinalizationDependencies) -> None:
        self._deps = dependencies

    async def finalize(self, context: PipelineFinalizationContext) -> None:
        try:
            if context.state.get("error"):
                context.summary["error"] = context.state.get("error")

            committed_records = dict(context.committed_records)
            committed_summary = self._deps.build_record_summary(committed_records)
            context.summary["total_urls"] = committed_summary["total_urls"]
            context.summary["success_count"] = committed_summary["success_count"]
            context.summary.update(
                self._deps.classify_pipeline_result(
                    total_urls=context.summary["total_urls"],
                    success_count=context.summary["success_count"],
                    state_error=context.state.get("error"),
                    validation_failures=context.validation_failures,
                )
            )
            self._deps.persist_pipeline_run(context, committed_records)
            for record in committed_records.values():
                record["durably_persisted"] = True
                record["record_source"] = "db"
            context.summary["durably_persisted"] = True
            self._deps.commit_items_file(context.items_path, committed_records)
            self._deps.write_summary(context.summary_path, context.summary)

            final_status = str(context.summary.get("execution_state") or "completed")
            await context.tracker.mark_done(final_status)
        finally:
            await context.sessions.stop()
