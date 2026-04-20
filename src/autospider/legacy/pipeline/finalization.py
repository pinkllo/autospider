"""Pipeline finalization helpers."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlparse

import yaml

from autospider.contexts.experience.application.handlers import (
    CollectionFinalizedHandler,
    CollectionFinalizedPayload,
)
from autospider.contexts.experience.application.skill_promotion import (
    SkillSedimenter,
)
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository as ExperienceSkillRepository,
)
from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed
from ...contexts.planning.domain import FATAL_CATEGORY

if TYPE_CHECKING:
    from ..domain.fields import FieldDefinition
    from .orchestration import PipelineRuntimeState, PipelineSessionBundle
    from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)
EXECUTION_STATE_COMPLETED = "completed"
EXECUTION_STATE_FAILED = "failed"
EXECUTION_STATE_INTERRUPTED = "interrupted"
OUTCOME_STATE_SUCCESS = "success"
OUTCOME_STATE_PARTIAL_SUCCESS = "partial_success"
OUTCOME_STATE_NO_DATA = "no_data"
OUTCOME_STATE_SYSTEM_FAILURE = "system_failure"
OUTCOME_STATE_INTERRUPTED = "interrupted"
DURABILITY_STATE_STAGED = "staged"
DURABILITY_STATE_DURABLE = "durable"
DURABILITY_STATE_FAILED_COMMIT = "failed_commit"
_LEARNING_PAYLOAD_FIELDS = (
    "world_snapshot",
    "site_profile_snapshot",
    "failure_patterns",
)


def _is_valid_xpath(xpath: object) -> bool:
    return isinstance(xpath, str) and xpath.strip().startswith("/")


def prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    valid_fields: list[dict] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for field_config in fields_config:
        if not isinstance(field_config, dict):
            continue

        field_name = str(field_config.get("name") or "").strip() or "<unknown>"
        xpath = field_config.get("xpath")
        required = bool(field_config.get("required", True))
        data_type = str(field_config.get("data_type") or "").strip().lower()
        source = str(field_config.get("extraction_source") or "").strip().lower()
        fixed_value = field_config.get("fixed_value")

        if _is_valid_xpath(xpath):
            normalized = dict(field_config)
            normalized["xpath"] = str(xpath).strip()
            valid_fields.append(normalized)
            continue

        if source in {"constant", "subtask_context"}:
            value = "" if fixed_value is None else str(fixed_value).strip()
            if value:
                normalized = dict(field_config)
                normalized["xpath"] = None
                normalized["extraction_source"] = source
                normalized["fixed_value"] = value
                valid_fields.append(normalized)
                continue

        if data_type == "url":
            normalized = dict(field_config)
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
    terminal_reason: str = "",
    failure_category: str = "",
    failure_detail: str = "",
) -> dict[str, object]:
    failed_count = max(total_urls - success_count, 0)
    success_rate = (success_count / total_urls) if total_urls > 0 else 0.0
    validation_failure_count = len(validation_failures)
    normalized_reason = str(terminal_reason or "").strip()
    normalized_failure_category = str(failure_category or "").strip()
    normalized_failure_detail = str(failure_detail or "").strip()

    if normalized_reason == "browser_intervention":
        execution_state = EXECUTION_STATE_INTERRUPTED
        outcome_state = OUTCOME_STATE_INTERRUPTED
    elif state_error:
        execution_state = EXECUTION_STATE_FAILED
        outcome_state = OUTCOME_STATE_SYSTEM_FAILURE
        normalized_reason = normalized_reason or str(state_error)
    elif total_urls <= 0:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_NO_DATA
        normalized_reason = normalized_reason or "no_data_collected"
    elif failed_count <= 0 and validation_failure_count == 0:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_SUCCESS
    else:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_PARTIAL_SUCCESS
        normalized_reason = normalized_reason or "partial_data_available"

    if outcome_state == OUTCOME_STATE_SUCCESS:
        promotion_state = "reusable"
    elif outcome_state == OUTCOME_STATE_INTERRUPTED:
        promotion_state = "rejected"
    elif success_count > 0:
        promotion_state = "diagnostic_only"
    else:
        promotion_state = "rejected"

    if not normalized_failure_category and outcome_state in {
        OUTCOME_STATE_SYSTEM_FAILURE,
        OUTCOME_STATE_INTERRUPTED,
    }:
        # 兜底：未打分类但 outcome 已是失败/中断，用 reason 作为 detail 方便上层展示。
        normalized_failure_detail = normalized_failure_detail or normalized_reason

    return {
        "execution_state": execution_state,
        "outcome_state": outcome_state,
        "terminal_reason": normalized_reason,
        "promotion_state": promotion_state,
        "success_rate": round(success_rate, 4),
        "failed_count": failed_count,
        "required_field_success_rate": round(success_rate, 4),
        "validation_failure_count": validation_failure_count,
        "failure_category": normalized_failure_category,
        "failure_detail": normalized_failure_detail,
    }


def should_promote_skill(
    *,
    state_error: object,
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    effective_error = _resolve_pipeline_error(state_error=state_error, summary=summary)
    if (
        not effective_error
        and str(summary.get("promotion_state") or "").strip().lower() == "reusable"
    ):
        return True

    classified = classify_pipeline_result(
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        state_error=effective_error,
        validation_failures=validation_failures,
        terminal_reason=str(summary.get("terminal_reason") or ""),
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


def _resolve_pipeline_error(*, state_error: object, summary: dict[str, Any]) -> str | None:
    state_message = str(state_error or "").strip()
    if state_message:
        return state_message
    summary_message = str(summary.get("error") or "").strip()
    return summary_message or None


def _refresh_summary_classification(
    *,
    classifier: Callable[..., dict[str, object]],
    summary: dict[str, Any],
    state_error: object,
    validation_failures: list[dict[str, Any]],
    failure_category: str = "",
    failure_detail: str = "",
) -> None:
    summary.update(
        classifier(
            total_urls=int(summary.get("total_urls", 0) or 0),
            success_count=int(summary.get("success_count", 0) or 0),
            state_error=_resolve_pipeline_error(state_error=state_error, summary=summary),
            validation_failures=validation_failures,
            terminal_reason=str(summary.get("terminal_reason") or ""),
            failure_category=str(failure_category or summary.get("failure_category") or ""),
            failure_detail=str(failure_detail or summary.get("failure_detail") or ""),
        )
    )


def promote_pipeline_skill(context: "PipelineFinalizationContext") -> Path | None:
    if not should_promote_skill(
        state_error=context.runtime_state.error,
        summary=context.summary,
        validation_failures=context.runtime_state.validation_failures,
    ):
        logger.info(
            "[Pipeline] 跳过 Skill 晋升: promotion_state=%s, success=%s/%s",
            str(context.summary.get("promotion_state") or ""),
            int(context.summary.get("success_count", 0) or 0),
            int(context.summary.get("total_urls", 0) or 0),
        )
        return None

    promoted_path = CollectionFinalizedHandler(SkillSedimenter(ExperienceSkillRepository())).handle(
        CollectionFinalizedPayload(
            run_id=str(context.summary.get("execution_id") or context.summary.get("run_id") or ""),
            plan_id=str(context.task_plan.get("plan_id") or ""),
            status=str(
                context.summary.get("outcome_state") or context.summary.get("execution_state") or ""
            ),
            artifacts_dir=context.output_dir,
        )
    )
    if promoted_path is None:
        logger.warning(
            "[Pipeline] Skill 晋升未生成有效结果: list_url=%s, task=%s",
            context.list_url,
            context.task_description[:120],
        )
        return None

    cleanup_output_draft_skill(context.list_url, context.output_dir)
    logger.info("[Pipeline] Skill 已晋升到正式目录: %s", promoted_path)
    return promoted_path


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


def _is_durable_record(record: dict[str, Any]) -> bool:
    return str(record.get("durability_state") or "").strip().lower() == DURABILITY_STATE_DURABLE


def _is_exportable_record(record: dict[str, Any]) -> bool:
    return bool(record.get("success")) and _is_durable_record(record)


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
        if _is_exportable_record(record)
    ]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    write_text_if_changed(items_path, payload)


async def finalize_task_from_record(task: Any, record: dict) -> None:
    if (
        bool(record.get("success"))
        and str(record.get("durability_state") or "") == DURABILITY_STATE_DURABLE
    ):
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


def _coerce_field_names(fields: list["FieldDefinition"]) -> list[str]:
    names: list[str] = []
    for field_definition in fields:
        name = str(getattr(field_definition, "name", "") or "").strip()
        if name:
            names.append(name)
    return names


def _coerce_dict_snapshot(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _coerce_failure_patterns(raw: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(raw or []) if isinstance(item, dict)]


def _resolve_world_snapshot(context: "PipelineFinalizationContext") -> dict[str, Any]:
    for candidate in (
        context.world_snapshot,
        context.summary.get("world_snapshot"),
        context.task_plan.get("world_snapshot"),
    ):
        snapshot = _coerce_dict_snapshot(candidate)
        if snapshot:
            return snapshot
    return {}


def _resolve_site_profile_snapshot(
    context: "PipelineFinalizationContext",
    world_snapshot: dict[str, Any],
) -> dict[str, Any]:
    for candidate in (
        context.site_profile_snapshot,
        context.summary.get("site_profile_snapshot"),
        context.task_plan.get("site_profile_snapshot"),
        world_snapshot.get("site_profile"),
    ):
        snapshot = _coerce_dict_snapshot(candidate)
        if snapshot:
            return snapshot
    return {}


def _resolve_failure_patterns(context: "PipelineFinalizationContext") -> list[dict[str, Any]]:
    world_snapshot = _resolve_world_snapshot(context)
    for candidate in (
        context.failure_patterns,
        world_snapshot.get("failure_patterns"),
        context.failure_records,
        context.summary.get("failure_patterns"),
        context.task_plan.get("failure_patterns"),
    ):
        patterns = _coerce_failure_patterns(candidate)
        if patterns:
            return patterns
    return []


def _build_task_run_payload_kwargs(
    context: "PipelineFinalizationContext",
    records: dict[str, dict],
) -> dict[str, Any]:
    world_snapshot = _resolve_world_snapshot(context)
    return {
        "normalized_url": "",
        "original_url": context.list_url,
        "page_state_signature": str(context.page_state_signature or ""),
        "anchor_url": str(context.anchor_url or ""),
        "variant_label": str(context.variant_label or ""),
        "task_description": context.task_description,
        "semantic_signature": str(context.semantic_signature or ""),
        "strategy_payload": dict(context.strategy_payload or {}),
        "field_names": _coerce_field_names(context.fields),
        "execution_id": str(
            context.summary.get("execution_id") or context.summary.get("run_id") or ""
        ),
        "thread_id": context.thread_id,
        "output_dir": context.output_dir,
        "pipeline_mode": str(context.summary.get("mode") or ""),
        "execution_state": str(context.summary.get("execution_state") or ""),
        "outcome_state": str(context.summary.get("outcome_state") or ""),
        "promotion_state": str(context.summary.get("promotion_state") or ""),
        "total_urls": int(context.summary.get("total_urls", 0) or 0),
        "success_count": int(context.summary.get("success_count", 0) or 0),
        "failed_count": int(context.summary.get("failed_count", 0) or 0),
        "validation_failure_count": int(context.summary.get("validation_failure_count", 0) or 0),
        "success_rate": float(context.summary.get("success_rate", 0.0) or 0.0),
        "error_message": str(context.summary.get("error") or ""),
        "summary_json": dict(context.summary or {}),
        "collection_config": dict(context.runtime_state.collection_config or {}),
        "extraction_config": dict(context.runtime_state.extraction_config or {}),
        "plan_knowledge": str(context.plan_knowledge or ""),
        "task_plan": dict(context.task_plan or {}),
        "plan_journal": list(context.plan_journal or []),
        "committed_records": list(records.values()),
        "validation_failures": list(context.runtime_state.validation_failures or []),
        "world_snapshot": world_snapshot,
        "site_profile_snapshot": _resolve_site_profile_snapshot(context, world_snapshot),
        "failure_patterns": _resolve_failure_patterns(context),
    }


def _instantiate_task_run_payload(payload_type: type, payload_kwargs: dict[str, Any]) -> Any:
    params = inspect.signature(payload_type).parameters.values()
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params):
        return payload_type(**payload_kwargs)

    supported = {
        name
        for name, param in inspect.signature(payload_type).parameters.items()
        if param.kind
        in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    missing_learning_fields = [
        name
        for name in _LEARNING_PAYLOAD_FIELDS
        if payload_kwargs.get(name) and name not in supported
    ]
    if missing_learning_fields:
        joined = ", ".join(sorted(missing_learning_fields))
        raise RuntimeError(f"TaskRunPayload missing learning snapshot fields: {joined}")
    return payload_type(**{key: value for key, value in payload_kwargs.items() if key in supported})


def _build_task_run_payload(
    context: "PipelineFinalizationContext",
    records: dict[str, dict],
):
    from ..common.db.repositories import TaskRunPayload
    from ..common.storage.task_run_query_service import normalize_url

    normalized_url = normalize_url(context.list_url)
    if not normalized_url:
        return None

    payload_kwargs = _build_task_run_payload_kwargs(context, records)
    payload_kwargs["normalized_url"] = normalized_url
    return _instantiate_task_run_payload(TaskRunPayload, payload_kwargs)


def persist_pipeline_records(
    context: "PipelineFinalizationContext", records: dict[str, dict]
) -> None:
    """将现版本运行结果持久化到 PostgreSQL。"""
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository
    from ..common.storage.task_run_query_service import invalidate_task_cache

    payload = _build_task_run_payload(context, records)
    if payload is None:
        return

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
    staging_items_path: Path
    staging_summary_path: Path
    committed_records: dict[str, dict[str, Any]]
    summary: dict[str, Any]
    runtime_state: "PipelineRuntimeState"
    plan_knowledge: str
    task_plan: dict[str, Any]
    plan_journal: list[dict[str, Any]]
    tracker: "TaskProgressTracker"
    sessions: "PipelineSessionBundle"
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    site_profile_snapshot: dict[str, Any] = field(default_factory=dict)
    failure_records: list[dict[str, Any]] = field(default_factory=list)
    failure_patterns: list[dict[str, Any]] = field(default_factory=list)
    semantic_signature: str = ""
    strategy_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PipelineFinalizationDependencies:
    build_record_summary: Callable[[dict[str, dict]], dict[str, int]]
    classify_pipeline_result: Callable[..., dict[str, object]]
    persist_pipeline_records: Callable[["PipelineFinalizationContext", dict[str, dict]], None]
    commit_items_file: Callable[[Path, dict[str, dict]], None]
    write_summary: Callable[[Path, dict], None]
    promote_output: Callable[[Path, Path], None]


class PipelineFinalizer:
    def __init__(self, dependencies: PipelineFinalizationDependencies) -> None:
        self._deps = dependencies

    async def finalize(self, context: PipelineFinalizationContext) -> None:
        try:
            if context.runtime_state.error:
                context.summary["error"] = context.runtime_state.error

            committed_records = dict(context.committed_records)
            committed_summary = normalize_record_summary(
                self._deps.build_record_summary(committed_records)
            )
            has_committed_records = bool(committed_records)
            all_records_durable = has_committed_records and all(
                _is_durable_record(record) for record in committed_records.values()
            )
            context.summary["total_urls"] = committed_summary["total_urls"]
            context.summary["success_count"] = committed_summary["success_count"]
            context.summary["failed_count"] = committed_summary["failed_count"]
            context.summary["durability_state"] = (
                DURABILITY_STATE_DURABLE if all_records_durable else DURABILITY_STATE_STAGED
            )
            context.summary["durably_persisted"] = all_records_durable
            context.summary["terminal_reason"] = str(
                context.summary.get("terminal_reason")
                or context.runtime_state.terminal_reason
                or ""
            )
            context.summary["failure_category"] = str(
                context.summary.get("failure_category")
                or context.runtime_state.failure_category
                or ""
            )
            context.summary["failure_detail"] = str(
                context.summary.get("failure_detail") or context.runtime_state.failure_detail or ""
            )
            _refresh_summary_classification(
                classifier=self._deps.classify_pipeline_result,
                summary=context.summary,
                state_error=context.runtime_state.error,
                validation_failures=context.runtime_state.validation_failures,
                failure_category=context.runtime_state.failure_category,
                failure_detail=context.runtime_state.failure_detail,
            )
            try:
                self._deps.commit_items_file(context.staging_items_path, committed_records)
                self._deps.write_summary(context.staging_summary_path, context.summary)
                self._deps.promote_output(context.staging_items_path, context.items_path)
                self._deps.promote_output(context.staging_summary_path, context.summary_path)
            except Exception as exc:  # noqa: BLE001
                logger.error("[Pipeline] export failed after durable commit: %s", exc)
                context.summary["error"] = str(exc)
                context.summary["export_state"] = "failed"
                context.summary["terminal_reason"] = str(
                    context.summary.get("terminal_reason") or "export_failed"
                )
                context.summary["failure_category"] = str(
                    context.summary.get("failure_category") or FATAL_CATEGORY
                )
                context.summary["failure_detail"] = str(
                    context.summary.get("failure_detail") or "export_failed"
                )
                _refresh_summary_classification(
                    classifier=self._deps.classify_pipeline_result,
                    summary=context.summary,
                    state_error=context.summary["error"],
                    validation_failures=context.runtime_state.validation_failures,
                    failure_category=str(context.summary.get("failure_category") or ""),
                    failure_detail=str(context.summary.get("failure_detail") or ""),
                )
                try:
                    self._deps.write_summary(context.summary_path, context.summary)
                except Exception as summary_exc:  # noqa: BLE001
                    logger.error(
                        "[Pipeline] failed to persist export failure summary: %s",
                        summary_exc,
                    )
            promoted_skill = promote_pipeline_skill(context)
            context.summary["skill_path"] = str(promoted_skill or "")
            context.summary["skill_state"] = "promoted" if promoted_skill else "skipped"
            self._deps.persist_pipeline_records(context, committed_records)

            final_status = str(context.summary.get("execution_state") or "completed")
            await context.tracker.mark_done(final_status)
        finally:
            await context.sessions.stop()
