from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autospider.contexts.planning.domain import PlanJournalEntry, PlanNode, PlanNodeType, TaskPlan
from autospider.composition.graph.controls import (
    PlanSpec,
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from autospider.composition.graph.world_model import (
    build_initial_world_model,
    upsert_page_model,
    world_model_to_payload,
)
from autospider.composition.pipeline.runtime_controls import resolve_concurrency_settings

ENTRY_JOURNAL_LIMIT = 3
PLANNER_STAGE = "planning_seeded"


def _select_entry_node(plan: TaskPlan) -> PlanNode | None:
    if plan.nodes:
        return plan.nodes[0]
    return None


def _resolve_page_type(node: PlanNode) -> str:
    node_type = getattr(node.node_type, "value", str(node.node_type or "")).strip().lower()
    if node_type == PlanNodeType.LEAF.value:
        return PlanNodeType.LIST_PAGE.value
    return node_type or PlanNodeType.CATEGORY.value


def _collect_entry_journal(plan: TaskPlan, node_id: str) -> list[dict[str, Any]]:
    matched = [entry for entry in plan.journal if str(entry.node_id or "") == node_id]
    return [_serialize_journal_entry(entry) for entry in matched[:ENTRY_JOURNAL_LIMIT]]


def _serialize_journal_entry(entry: PlanJournalEntry) -> dict[str, Any]:
    return {
        "phase": entry.phase,
        "action": entry.action,
        "reason": entry.reason,
        "evidence": entry.evidence,
        "metadata": dict(entry.metadata or {}),
        "created_at": entry.created_at,
    }


def _build_page_metadata(plan: TaskPlan, node: PlanNode) -> dict[str, Any]:
    return {
        "name": node.name,
        "anchor_url": str(node.anchor_url or node.url or ""),
        "page_state_signature": str(node.page_state_signature or ""),
        "variant_label": str(node.variant_label or ""),
        "task_description": node.task_description,
        "observations": node.observations,
        "context": dict(node.context or {}),
        "nav_steps": list(node.nav_steps or []),
        "shared_fields": [dict(field) for field in list(plan.shared_fields or [])],
        "journal_summary": _collect_entry_journal(plan, node.node_id),
    }


def _build_page_models(plan: TaskPlan) -> dict[str, dict[str, Any]]:
    page_models: dict[str, dict[str, Any]] = {}
    fallback_links = max(len(plan.subtasks), 0)
    for node in plan.nodes:
        url = str(node.url or node.anchor_url or plan.site_url or "")
        page_models[node.node_id] = {
            "page_id": node.node_id,
            "url": url,
            "page_type": _resolve_page_type(node),
            "links": int(node.children_count or fallback_links),
            "depth": int(node.depth or 0),
            "metadata": _build_page_metadata(plan, node),
        }
    return page_models


def _resolve_dispatch_policy(request_params: Mapping[str, Any] | None) -> dict[str, Any]:
    default = build_default_dispatch_policy()
    concurrency = resolve_concurrency_settings(dict(request_params or {}))
    max_concurrency = int(concurrency.max_concurrent or default.max_concurrency)
    strategy = "parallel" if max_concurrency > 1 else default.strategy
    return {
        "strategy": strategy,
        "max_concurrency": max_concurrency,
        "reason": "根据规划阶段可执行上下文确定的调度策略",
    }


def _resolve_recovery_policy() -> dict[str, Any]:
    default = build_default_recovery_policy()
    return {
        "max_retries": default.max_retries,
        "max_replans": default.max_replans,
        "fail_fast": default.fail_fast,
        "escalation_categories": list(default.escalation_categories),
        "reason": "使用默认恢复策略等待执行阶段累积失败记录后再调整",
    }


def build_planner_world_payload(
    plan: TaskPlan,
    *,
    request_params: Mapping[str, Any] | None = None,
    failure_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_failures = [dict(item) for item in list(failure_records or [])]
    world_model = build_initial_world_model(
        request_params=request_params,
        page_models=_build_page_models(plan),
        failure_records=list(resolved_failures),
    )
    entry_node = _select_entry_node(plan)
    if entry_node is not None and entry_node.node_id not in world_model.page_models:
        world_model = upsert_page_model(
            world_model,
            page_id=entry_node.node_id,
            url=str(entry_node.url or entry_node.anchor_url or plan.site_url or ""),
            page_type=_resolve_page_type(entry_node),
            links=int(entry_node.children_count or len(plan.subtasks)),
            depth=int(entry_node.depth or 0),
            metadata=_build_page_metadata(plan, entry_node),
        )
    return {
        "request_params": dict(request_params or {}),
        "world_model": world_model_to_payload(world_model),
        "failure_records": list(resolved_failures),
    }


def build_planner_control_payload(
    plan: TaskPlan,
    *,
    request_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry_node = _select_entry_node(plan)
    current_plan = PlanSpec(
        goal=str(getattr(entry_node, "task_description", "") or plan.original_request or ""),
        page_id=str(getattr(entry_node, "node_id", "") or ""),
        stage=PLANNER_STAGE,
        metadata={
            "entry_url": str(getattr(entry_node, "url", "") or plan.site_url or ""),
            "site_url": str(plan.site_url or ""),
            "total_subtasks": int(plan.total_subtasks or len(plan.subtasks)),
        },
    )
    return {
        "current_plan": {
            "goal": current_plan.goal,
            "page_id": current_plan.page_id,
            "stage": current_plan.stage,
            "metadata": dict(current_plan.metadata),
        },
        "dispatch_policy": _resolve_dispatch_policy(request_params),
        "recovery_policy": _resolve_recovery_policy(),
    }
