"""Task-run payload and persistence helpers for finalization."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from autospider.contexts.collection.domain.fields import FieldDefinition
    from .finalization import PipelineFinalizationContext

_LEARNING_PAYLOAD_FIELDS = (
    "world_snapshot",
    "site_profile_snapshot",
    "failure_patterns",
)


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


def build_task_run_payload(
    context: "PipelineFinalizationContext",
    records: dict[str, dict],
):
    from autospider.platform.persistence.sql.orm.repositories import TaskRunPayload
    from autospider.platform.persistence.task_lookup import normalize_url

    normalized_url = normalize_url(context.list_url)
    if not normalized_url:
        return None

    payload_kwargs = _build_task_run_payload_kwargs(context, records)
    payload_kwargs["normalized_url"] = normalized_url
    return _instantiate_task_run_payload(TaskRunPayload, payload_kwargs)


def persist_pipeline_records(
    context: "PipelineFinalizationContext",
    records: dict[str, dict],
) -> None:
    from autospider.platform.persistence.sql.orm.engine import session_scope
    from autospider.platform.persistence.sql.orm.repositories import TaskRunWriteRepository
    from autospider.platform.persistence.task_run_query_service import invalidate_task_cache

    payload = build_task_run_payload(context, records)
    if payload is None:
        return

    with session_scope() as session:
        repo = TaskRunWriteRepository(session)
        repo.save_run(payload)
    invalidate_task_cache(context.list_url)
