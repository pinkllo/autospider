"""Chat 澄清任务到执行参数的交接辅助。"""

from __future__ import annotations

from typing import Any

from autospider.platform.shared_kernel.grouping_semantics import normalize_grouping_semantics
from autospider.contexts.collection.domain.fields import FieldDefinition
from ..pipeline.helpers import resolve_semantic_identity
from ..pipeline.runtime_controls import resolve_concurrency_settings


def _field_to_dict(field: Any) -> dict[str, Any]:
    if isinstance(field, FieldDefinition):
        return {
            "name": field.name,
            "description": field.description,
            "required": field.required,
            "data_type": field.data_type,
            "example": field.example,
        }
    if isinstance(field, dict):
        return {
            "name": str(field.get("name") or ""),
            "description": str(field.get("description") or ""),
            "required": bool(field.get("required", True)),
            "data_type": str(field.get("data_type") or "text"),
            "example": field.get("example"),
        }
    return {}


def _coalesce_cli_option(cli_args: dict[str, Any], key: str, fallback: Any) -> Any:
    value = cli_args.get(key)
    return fallback if value is None else value


def _is_serial_mode_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_serial_mode_overrides(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params or {})
    serial_mode = _is_serial_mode_enabled(normalized.get("serial_mode"))
    normalized["serial_mode"] = serial_mode
    if not serial_mode:
        return normalized
    normalized["consumer_concurrency"] = 1
    normalized["max_concurrent"] = 1
    return normalized


def _ensure_runtime_payload_slots(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params or {})
    normalized.setdefault("decision_context", {})
    normalized.setdefault("world_snapshot", {})
    normalized.setdefault("control_snapshot", {})
    normalized.setdefault("failure_records", [])
    return normalized


def _resolve_semantic_identity(task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return resolve_semantic_identity(task)


def build_chat_review_payload(
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    dispatch_mode: str,
) -> dict[str, Any]:
    cli_args = dict(state.get("cli_args") or {})
    clarified_task = dict(task)
    clarified_task.update(normalize_grouping_semantics(task))
    semantic_signature, strategy_payload = _resolve_semantic_identity(clarified_task)
    clarified_task["semantic_signature"] = semantic_signature
    clarified_task["strategy_payload"] = strategy_payload
    clarified_task["matched_registry_id"] = str(task.get("matched_registry_id") or "")
    base_options = _apply_serial_mode_overrides(
        {
            "max_pages": _coalesce_cli_option(
                cli_args, "max_pages", clarified_task.get("max_pages")
            ),
            "target_url_count": _coalesce_cli_option(
                cli_args,
                "target_url_count",
                clarified_task.get("target_url_count"),
            ),
            "consumer_concurrency": _coalesce_cli_option(
                cli_args,
                "consumer_concurrency",
                clarified_task.get("consumer_concurrency"),
            ),
            "field_explore_count": _coalesce_cli_option(
                cli_args,
                "field_explore_count",
                clarified_task.get("field_explore_count"),
            ),
            "field_validate_count": _coalesce_cli_option(
                cli_args,
                "field_validate_count",
                clarified_task.get("field_validate_count"),
            ),
            "pipeline_mode": cli_args.get("pipeline_mode") or "redis",
            "execution_mode": dispatch_mode,
            "headless": cli_args["headless"] if "headless" in cli_args else None,
            "output_dir": str(cli_args.get("output_dir") or "output"),
            "serial_mode": cli_args.get("serial_mode"),
            "max_concurrent": _coalesce_cli_option(cli_args, "max_concurrent", None),
            "global_browser_budget": cli_args.get("global_browser_budget"),
        }
    )
    concurrency = resolve_concurrency_settings(base_options)
    effective_options = dict(base_options)
    effective_options["consumer_concurrency"] = concurrency.consumer_concurrency
    effective_options["max_concurrent"] = concurrency.max_concurrent
    effective_options["global_browser_budget"] = concurrency.global_browser_budget
    return {
        "type": "chat_review",
        "thread_id": str(
            (state.get("meta") or {}).get("thread_id") or state.get("thread_id") or ""
        ),
        "clarified_task": clarified_task,
        "effective_options": effective_options,
    }


def build_chat_execution_params(
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    dispatch_mode: str,
) -> dict[str, Any]:
    cli_args = dict(state.get("cli_args") or {})
    grouping = normalize_grouping_semantics(task)
    semantic_signature, strategy_payload = _resolve_semantic_identity(task)
    base_params = _apply_serial_mode_overrides(
        {
            "list_url": task.get("list_url", ""),
            "task_description": task.get("task_description", ""),
            "semantic_signature": semantic_signature,
            "strategy_payload": strategy_payload,
            "matched_registry_id": str(task.get("matched_registry_id") or ""),
            "fields": [_field_to_dict(item) for item in task.get("fields", [])],
            **grouping,
            "max_pages": _coalesce_cli_option(cli_args, "max_pages", task.get("max_pages")),
            "target_url_count": _coalesce_cli_option(
                cli_args,
                "target_url_count",
                task.get("target_url_count"),
            ),
            "consumer_concurrency": _coalesce_cli_option(
                cli_args,
                "consumer_concurrency",
                task.get("consumer_concurrency"),
            ),
            "field_explore_count": _coalesce_cli_option(
                cli_args,
                "field_explore_count",
                task.get("field_explore_count"),
            ),
            "field_validate_count": _coalesce_cli_option(
                cli_args,
                "field_validate_count",
                task.get("field_validate_count"),
            ),
            "pipeline_mode": cli_args.get("pipeline_mode"),
            "headless": cli_args["headless"] if "headless" in cli_args else None,
            "output_dir": str(cli_args.get("output_dir") or "output"),
            "serial_mode": cli_args.get("serial_mode"),
            "request": str(cli_args.get("request") or task.get("task_description") or ""),
            "max_concurrent": _coalesce_cli_option(cli_args, "max_concurrent", None),
            "execution_mode_resolved": dispatch_mode,
            "runtime_subtask_max_children": cli_args.get("runtime_subtask_max_children"),
            "runtime_subtasks_use_main_model": cli_args.get("runtime_subtasks_use_main_model"),
            "selected_skills": list((state.get("conversation") or {}).get("selected_skills") or []),
            "global_browser_budget": cli_args.get("global_browser_budget"),
        }
    )
    concurrency = resolve_concurrency_settings(base_params)
    normalized = _ensure_runtime_payload_slots(base_params)
    normalized["consumer_concurrency"] = concurrency.consumer_concurrency
    normalized["max_concurrent"] = concurrency.max_concurrent
    normalized["global_browser_budget"] = concurrency.global_browser_budget
    return normalized
