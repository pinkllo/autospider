"""Pipeline finalization facade and coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from autospider.contexts.planning.domain import FATAL_CATEGORY
from autospider.platform.observability.logger import get_logger

from .finalization_artifacts import (
    build_execution_id,
    build_record_summary,
    build_run_record,
    commit_items_file,
    finalize_task_from_record,
    is_durable_record as _is_durable_record,
    load_persisted_run_records,
    normalize_record_summary,
    prepare_pipeline_output,
    promote_staged_output,
    write_summary,
)
from .finalization_payloads import (
    build_task_run_payload as _build_task_run_payload,
    persist_pipeline_records,
)
from .finalization_skill import (
    cleanup_output_draft_skill,
    find_output_draft_skill,
    promote_pipeline_skill as _promote_pipeline_skill_impl,
    strip_draft_markers_from_skill_content,
)
from .finalization_status import (
    DURABILITY_STATE_DURABLE,
    DURABILITY_STATE_FAILED_COMMIT,
    DURABILITY_STATE_STAGED,
    classify_pipeline_result,
    refresh_summary_classification as _refresh_summary_classification,
    should_promote_skill,
)

if TYPE_CHECKING:
    from autospider.contexts.collection.domain.fields import FieldDefinition
    from .orchestration import PipelineRuntimeState, PipelineSessionBundle
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


def promote_pipeline_skill(context: "PipelineFinalizationContext") -> Path | None:
    return _promote_pipeline_skill_impl(
        context,
        should_promote_skill_fn=should_promote_skill,
        cleanup_output_draft_skill_fn=cleanup_output_draft_skill,
    )


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

    def _apply_committed_record_summary(
        self,
        context: PipelineFinalizationContext,
        committed_records: dict[str, dict[str, Any]],
    ) -> None:
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

    def _apply_runtime_state(self, context: PipelineFinalizationContext) -> None:
        if context.runtime_state.error:
            context.summary["error"] = context.runtime_state.error
        context.summary["terminal_reason"] = str(
            context.summary.get("terminal_reason") or context.runtime_state.terminal_reason or ""
        )
        context.summary["failure_category"] = str(
            context.summary.get("failure_category") or context.runtime_state.failure_category or ""
        )
        context.summary["failure_detail"] = str(
            context.summary.get("failure_detail") or context.runtime_state.failure_detail or ""
        )

    def _refresh_classification(self, context: PipelineFinalizationContext) -> None:
        _refresh_summary_classification(
            classifier=self._deps.classify_pipeline_result,
            summary=context.summary,
            state_error=context.runtime_state.error,
            validation_failures=context.runtime_state.validation_failures,
            failure_category=context.runtime_state.failure_category,
            failure_detail=context.runtime_state.failure_detail,
        )

    def _handle_export_failure(self, context: PipelineFinalizationContext, error: Exception) -> None:
        logger.error("[Pipeline] export failed after durable commit: %s", error)
        context.summary["error"] = str(error)
        context.summary["export_state"] = DURABILITY_STATE_FAILED_COMMIT
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
            logger.error("[Pipeline] failed to persist export failure summary: %s", summary_exc)

    def _export_artifacts(
        self,
        context: PipelineFinalizationContext,
        committed_records: dict[str, dict[str, Any]],
    ) -> None:
        try:
            self._deps.commit_items_file(context.staging_items_path, committed_records)
            self._deps.write_summary(context.staging_summary_path, context.summary)
            self._deps.promote_output(context.staging_items_path, context.items_path)
            self._deps.promote_output(context.staging_summary_path, context.summary_path)
        except Exception as exc:  # noqa: BLE001
            self._handle_export_failure(context, exc)

    def _persist_and_mark_done(
        self,
        context: PipelineFinalizationContext,
        committed_records: dict[str, dict[str, Any]],
    ) -> None:
        promoted_skill = promote_pipeline_skill(context)
        context.summary["skill_path"] = str(promoted_skill or "")
        context.summary["skill_state"] = "promoted" if promoted_skill else "skipped"
        self._deps.persist_pipeline_records(context, committed_records)

    async def finalize(self, context: PipelineFinalizationContext) -> None:
        try:
            committed_records = dict(context.committed_records)
            self._apply_committed_record_summary(context, committed_records)
            self._apply_runtime_state(context)
            self._refresh_classification(context)
            self._export_artifacts(context, committed_records)
            self._persist_and_mark_done(context, committed_records)
            final_status = str(context.summary.get("execution_state") or "completed")
            await context.tracker.mark_done(final_status)
        finally:
            await context.sessions.stop()
