"""Shared builders for chat review payloads and execution handoff params."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..pipeline.runtime_controls import resolve_concurrency_settings

_PIPELINE_MODE_REDIS = "redis"


def _coalesce_cli_option(cli_args: Mapping[str, Any], key: str, fallback: Any) -> Any:
    value = cli_args.get(key)
    return fallback if value is None else value


def _is_serial_mode_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def apply_serial_mode_overrides(params: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(params or {})
    serial_mode = _is_serial_mode_enabled(normalized.get("serial_mode"))
    normalized["serial_mode"] = serial_mode
    if not serial_mode:
        return normalized
    normalized["consumer_concurrency"] = 1
    normalized["max_concurrent"] = 1
    return normalized


def _normalize_runtime_controls(params: Mapping[str, Any]) -> dict[str, Any]:
    normalized = apply_serial_mode_overrides(params)
    concurrency = resolve_concurrency_settings(normalized)
    normalized["consumer_concurrency"] = concurrency.consumer_concurrency
    normalized["max_concurrent"] = concurrency.max_concurrent
    normalized["global_browser_budget"] = concurrency.global_browser_budget
    return normalized


def build_chat_review_payload(
    *,
    thread_id: str,
    cli_args: Mapping[str, Any] | None,
    task: Mapping[str, Any] | None,
    dispatch_mode: str,
) -> dict[str, Any]:
    resolved_cli_args = dict(cli_args or {})
    resolved_task = dict(task or {})
    effective_options = _normalize_runtime_controls(
        {
            "max_pages": _coalesce_cli_option(resolved_cli_args, "max_pages", resolved_task.get("max_pages")),
            "target_url_count": _coalesce_cli_option(
                resolved_cli_args,
                "target_url_count",
                resolved_task.get("target_url_count"),
            ),
            "consumer_concurrency": _coalesce_cli_option(
                resolved_cli_args,
                "consumer_concurrency",
                resolved_task.get("consumer_concurrency"),
            ),
            "field_explore_count": _coalesce_cli_option(
                resolved_cli_args,
                "field_explore_count",
                resolved_task.get("field_explore_count"),
            ),
            "field_validate_count": _coalesce_cli_option(
                resolved_cli_args,
                "field_validate_count",
                resolved_task.get("field_validate_count"),
            ),
            "pipeline_mode": _PIPELINE_MODE_REDIS,
            "execution_mode": dispatch_mode,
            "headless": resolved_cli_args["headless"] if "headless" in resolved_cli_args else None,
            "output_dir": str(resolved_cli_args.get("output_dir") or "output"),
            "serial_mode": resolved_cli_args.get("serial_mode"),
            "max_concurrent": _coalesce_cli_option(resolved_cli_args, "max_concurrent", None),
            "global_browser_budget": resolved_cli_args.get("global_browser_budget"),
        }
    )
    return {
        "type": "chat_review",
        "thread_id": str(thread_id or ""),
        "clarified_task": resolved_task,
        "effective_options": effective_options,
    }


def build_chat_execution_params(
    *,
    cli_args: Mapping[str, Any] | None,
    task: Mapping[str, Any] | None,
    dispatch_mode: str,
    selected_skills: list[dict[str, str]] | None,
) -> dict[str, Any]:
    resolved_cli_args = dict(cli_args or {})
    resolved_task = dict(task or {})
    normalized = _normalize_runtime_controls(
        {
            "list_url": resolved_task.get("list_url", ""),
            "task_description": resolved_task.get("task_description", ""),
            "fields": [
                dict(item)
                for item in list(resolved_task.get("fields") or [])
                if isinstance(item, Mapping)
            ],
            "max_pages": _coalesce_cli_option(resolved_cli_args, "max_pages", resolved_task.get("max_pages")),
            "target_url_count": _coalesce_cli_option(
                resolved_cli_args,
                "target_url_count",
                resolved_task.get("target_url_count"),
            ),
            "consumer_concurrency": _coalesce_cli_option(
                resolved_cli_args,
                "consumer_concurrency",
                resolved_task.get("consumer_concurrency"),
            ),
            "field_explore_count": _coalesce_cli_option(
                resolved_cli_args,
                "field_explore_count",
                resolved_task.get("field_explore_count"),
            ),
            "field_validate_count": _coalesce_cli_option(
                resolved_cli_args,
                "field_validate_count",
                resolved_task.get("field_validate_count"),
            ),
            "pipeline_mode": _PIPELINE_MODE_REDIS,
            "headless": resolved_cli_args["headless"] if "headless" in resolved_cli_args else None,
            "output_dir": str(resolved_cli_args.get("output_dir") or "output"),
            "serial_mode": resolved_cli_args.get("serial_mode"),
            "request": str(resolved_cli_args.get("request") or resolved_task.get("task_description") or ""),
            "max_concurrent": _coalesce_cli_option(resolved_cli_args, "max_concurrent", None),
            "execution_mode_resolved": dispatch_mode,
            "runtime_subtask_max_children": resolved_cli_args.get("runtime_subtask_max_children"),
            "runtime_subtasks_use_main_model": resolved_cli_args.get("runtime_subtasks_use_main_model"),
            "selected_skills": list(selected_skills or []),
            "global_browser_budget": resolved_cli_args.get("global_browser_budget"),
        }
    )
    return normalized


__all__ = [
    "apply_serial_mode_overrides",
    "build_chat_execution_params",
    "build_chat_review_payload",
]
