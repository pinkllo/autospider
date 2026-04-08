"""Application-level request/context helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..common.config import config
from ..common.storage.idempotent_io import write_json_idempotent
from ..common.storage.persistence import CollectionConfig
from ..contracts import ExecutionContext, ExecutionRequest, InfraConfig, PipelineMode, TaskIdentity
from ..domain.fields import FieldDefinition
from ..pipeline.runtime_controls import resolve_concurrency_settings


def build_field_definitions(raw_fields: list[dict[str, Any]]) -> list[FieldDefinition]:
    fields: list[FieldDefinition] = []
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        fields.append(
            FieldDefinition(
                name=str(raw.get("name") or ""),
                description=str(raw.get("description") or ""),
                required=bool(raw.get("required", True)),
                data_type=str(raw.get("data_type") or "text"),
                example=raw.get("example"),
            )
        )
    return fields


def build_artifact(label: str, path: str | Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}


def build_execution_request(
    params: dict[str, Any],
    *,
    thread_id: str,
    guard_intervention_mode: str = "interrupt",
) -> ExecutionRequest:
    return ExecutionRequest.from_params(
        dict(params or {}),
        thread_id=thread_id,
        guard_intervention_mode=guard_intervention_mode,
    )


def build_infra_config() -> InfraConfig:
    pipeline_mode = str(config.pipeline.mode or PipelineMode.REDIS.value).strip().lower()
    return InfraConfig(
        browser_headless_default=bool(config.browser.headless),
        browser_timeout_ms=int(config.browser.timeout_ms or 30000),
        pipeline_mode_default=PipelineMode(pipeline_mode),
        pipeline_consumer_concurrency=int(config.pipeline.consumer_concurrency or 1),
        planner_max_concurrent_subtasks=int(config.planner.max_concurrent_subtasks or 1),
        redis_enabled=bool(config.redis.enabled),
        checkpoint_enabled=bool(config.graph_checkpoint.enabled),
    )


def build_execution_context(
    request: ExecutionRequest,
    *,
    fields: list[Any] | None = None,
) -> ExecutionContext:
    identity = TaskIdentity(
        list_url=str(request.list_url or "").strip(),
        anchor_url=str(request.anchor_url or "").strip(),
        page_state_signature=str(request.page_state_signature or "").strip(),
        variant_label=str(request.variant_label or "").strip(),
        task_description=str(request.task_description or "").strip(),
        field_names=tuple(
            str(item.get("name") or "").strip()
            for item in list(request.fields or [])
            if str(item.get("name") or "").strip()
        ),
    )
    resolved = resolve_concurrency_settings(
        {
            "serial_mode": request.serial_mode,
            "consumer_concurrency": request.consumer_concurrency,
            "max_concurrent": request.max_concurrent,
            "global_browser_budget": request.global_browser_budget,
        }
    )
    infra = build_infra_config()
    pipeline_mode = request.pipeline_mode or infra.pipeline_mode_default
    execution_id = str(request.execution_id or "").strip()
    return ExecutionContext(
        request=request,
        identity=identity,
        fields=tuple(list(fields or [])),
        pipeline_mode=pipeline_mode,
        consumer_concurrency=resolved.consumer_concurrency,
        max_concurrent=resolved.max_concurrent,
        global_browser_budget=resolved.global_browser_budget,
        resume_mode=request.resume_mode,
        execution_id=execution_id,
        selected_skills=tuple(list(request.selected_skills or [])),
        plan_knowledge=str(request.plan_knowledge or ""),
        task_plan_snapshot=dict(request.task_plan_snapshot or {}),
        plan_journal=tuple(list(request.plan_journal or [])),
        initial_nav_steps=tuple(list(request.initial_nav_steps or [])),
    )


def materialize_collection_config(output_dir: str | Path, collection_config: dict[str, Any]) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "collection_config.json"
    normalized = CollectionConfig.from_dict(dict(collection_config or {})).to_dict()
    write_json_idempotent(
        config_path,
        normalized,
        identity_keys=("list_url", "page_state_signature", "anchor_url", "variant_label", "task_description"),
    )
    return config_path


def serialize_xpath_result(raw_result: Any) -> dict[str, Any] | None:
    if not isinstance(raw_result, dict):
        return None
    return {
        "fields": list(raw_result.get("fields") or []),
        "records": list(raw_result.get("records") or []),
        "total_urls": int(raw_result.get("total_urls", 0) or 0),
        "success_count": int(raw_result.get("success_count", 0) or 0),
    }
