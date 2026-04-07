from __future__ import annotations

from datetime import datetime
import operator
from pathlib import Path
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send, interrupt

from ...common.browser.intervention import BrowserInterventionRequired
from ...common.config import config
from ...contracts import ExpandRequest, PipelineMode, SubtaskOutcomeType
from ...domain.planning import ExecutionBrief, PlanJournalEntry, SubTask, SubTaskMode, SubTaskStatus, TaskPlan
from ...crawler.planner.planner_artifacts import PlannerArtifacts
from ...pipeline.worker import SubTaskWorker
from ...pipeline.runtime_controls import resolve_concurrency_settings
from ...services import PlanMutationService


def _use_last(existing: Any, new: Any) -> Any:
    """Reducer：并行分支 Fan-in 时取最后到达的值（用于所有分支值相同的只读透传字段）。"""
    return new


class MultiDispatchState(TypedDict, total=False):
    """主调度图的状态字典定义。

    用于在上层 Dispatch 调度引擎中维护多任务并行执行的全局环境和结果聚合槽。
    带有 Annotated[..., operator.add] 声明的字段，在运行时由 LangGraph 执行自动合并操作，
    而不是默认的覆盖逻辑。
    """
    thread_id: str  # 当前图运行的唯一线程 ID，用于绑定执行上下文或断点恢复
    normalized_params: Annotated[dict[str, Any], _use_last]  # 经过统一归一化后的运行参数（例如从 CLI 或 API 传入的全局配置）
    task_plan: Annotated[TaskPlan, _use_last]  # 全局任务规划数据结构，包含了待调度的所有子任务树
    plan_knowledge: Annotated[str, _use_last]  # 规划阶段产出的 DFS 知识文档正文
    dispatch_queue: list[dict[str, Any]]  # 尚未下发执行的子任务队列（等待进入下一批并行）
    current_batch: list[dict[str, Any]]  # 目前正被 Send API 分发在当前轮次被并行处理的一批子任务
    
    # 采用 operator.add 作为 Reducer，并行执行的多任务产生结果时自动合并 list，防止互相覆盖
    round_subtask_results: Annotated[list[dict[str, Any]], operator.add]  # 当前轮次 fan-in 回来的结果
    subtask_results: Annotated[list[dict[str, Any]], _use_last]  # 累计结果，仅在 merge 节点更新
    round_expand_requests: Annotated[list[dict[str, Any]], operator.add]  # 当前轮次运行时扩树请求
    artifacts: Annotated[list[dict[str, str]], operator.add]  # 聚合所有子图节点在运行过程中产生的数据产物（如 JSON/截图 文件路径）
    
    dispatch_result: dict[str, Any]  # 全部调度完毕后最终生成的调度汇总报告
    summary: dict[str, Any]  # 给全局提供各节点运行状态概览的数据集（用于上层获取进展统计）
    node_status: str  # 当前节点或图的执行结果状态，例如 "ok" 或 "fatal"
    node_payload: dict[str, Any]  # 携带该图计算产出的核心数据或载荷给后续节点
    node_error: dict[str, str] | None  # 记录致命的流程中断或解析错误信息


class SubTaskFlowState(TypedDict, total=False):
    """单个子任务流执行的状态定义。

    作为 multi_dispatch 子节点启动的独立执行栈，维护单一子任务的状态。
    """
    normalized_params: dict[str, Any]  # 从主图透传的全局运行时环境参数（含 _thread_id）
    task_plan: TaskPlan  # 包含基础配置的全局规划对象（只读，为 worker 提供字段引用背景等）
    plan_knowledge: str  # 规划阶段的 DFS 知识文档正文
    subtask_payload: dict[str, Any]  # 被分配到当前分片节点运行的目标子任务配置字典
    subtask_result: dict[str, Any]   # 记录当前单独这个子任务完成后的成功与否及提取数量等结果信息
    
    # 类似上层，利用 operator.add 支持在流中合并多次步骤生成的产物（例如被重新规划出多个）
    round_expand_requests: Annotated[list[dict[str, Any]], operator.add]  # 运行时扩树请求
    round_subtask_results: Annotated[list[dict[str, Any]], operator.add]  # 向下个 finalize 节点投递本轮结果
    artifacts: Annotated[list[dict[str, str]], operator.add]  # 该子任务保存到本地结果等记录的制品文件信息

def _artifact(label: str, path: str | Path) -> dict[str, str]:
    """快捷构造标准附件制品的字典记录。"""
    return {"label": label, "path": str(path)}


def _subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """生成子任务唯一特征指纹。"""
    return (
        str(payload.get("page_state_signature") or "").strip(),
        str(payload.get("anchor_url") or "").strip(),
        str(payload.get("variant_label") or "").strip(),
        str(payload.get("task_description") or "").strip(),
        str(payload.get("parent_id") or "").strip(),
    )


def _restore_subtask(payload: dict[str, Any]) -> SubTask:
    """从纯字典结构安全反序列化还原回 SubTask 模型实例。"""
    return SubTask.model_validate(dict(payload or {}))


def _inherit_parent_nav_steps(payload: dict[str, Any], plan: TaskPlan) -> dict[str, Any]:
    """为运行时派生子任务补齐父导航链。"""
    hydrated = dict(payload or {})
    if hydrated.get("nav_steps"):
        return hydrated

    parent_id = str(hydrated.get("parent_id") or "").strip()
    if not parent_id:
        return hydrated

    for subtask in plan.subtasks:
        if subtask.id != parent_id:
            continue
        hydrated["nav_steps"] = list(subtask.nav_steps or [])
        return hydrated
    return hydrated


def _resolve_runtime_replan_max_children(params: dict[str, Any]) -> int:
    default_value = int(config.planner.runtime_subtasks_max_children or 0)
    raw_value = params.get("runtime_subtask_max_children")
    try:
        resolved = int(raw_value) if raw_value is not None else default_value
    except (TypeError, ValueError):
        resolved = default_value
    return max(0, resolved)


def _resolve_runtime_subtasks_use_main_model(params: dict[str, Any]) -> bool:
    default_value = bool(config.planner.runtime_subtasks_use_main_model)
    raw_value = params.get("runtime_subtasks_use_main_model")
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off", ""}


def _resolve_dispatch_batch_size(state: MultiDispatchState) -> int:
    params = dict(state.get("normalized_params") or {})
    return resolve_concurrency_settings(params).max_concurrent




def _is_reliable_subtask_result(result: dict[str, Any] | None) -> bool:
    summary = dict((result or {}).get("summary") or {})
    outcome_type = str((result or {}).get("outcome_type") or "").strip().lower()
    if outcome_type in {SubtaskOutcomeType.NO_DATA.value, SubtaskOutcomeType.EXPANDED.value}:
        return False
    execution_state = str(summary.get("execution_state") or "").strip().lower()
    durability_state = str(summary.get("durability_state") or "").strip().lower()
    if execution_state and execution_state != "completed":
        return False
    return durability_state == "durable"


def _resolve_subtask_status(result: dict[str, Any]) -> SubTaskStatus:
    outcome_type = str(result.get("outcome_type") or "").strip().lower()
    if outcome_type == SubtaskOutcomeType.EXPANDED.value:
        return SubTaskStatus.EXPANDED
    if outcome_type == SubtaskOutcomeType.NO_DATA.value:
        return SubTaskStatus.NO_DATA
    if outcome_type == SubtaskOutcomeType.SYSTEM_FAILURE.value:
        return SubTaskStatus.SYSTEM_FAILURE
    if outcome_type == SubtaskOutcomeType.BUSINESS_FAILURE.value:
        return SubTaskStatus.BUSINESS_FAILURE
    execution_state = str(result.get("execution_state") or "").strip().lower()
    outcome_state = str(result.get("outcome_state") or "").strip().lower()
    durability_state = str(result.get("durability_state") or "").strip().lower()
    error = str(result.get("error") or "").strip()
    if execution_state == SubTaskStatus.EXPANDED.value:
        return SubTaskStatus.EXPANDED
    if outcome_state == "no_data":
        return SubTaskStatus.NO_DATA
    if error or outcome_state == "system_failure" or execution_state == "failed":
        return SubTaskStatus.SYSTEM_FAILURE
    if durability_state != "durable":
        return SubTaskStatus.SYSTEM_FAILURE
    if int(result.get("failed_count", 0) or 0) > 0:
        return SubTaskStatus.BUSINESS_FAILURE
    return SubTaskStatus.COMPLETED


def _build_subtask_result(
    subtask: SubTask,
    *,
    status: SubTaskStatus,
    error: str = "",
    result: dict[str, Any] | None = None,
    expand_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """标准化构建包含运行状态及其结果文件等核心指标的子任务结果字典。"""
    run_result = dict(result or {})
    outcome_type = str(run_result.get("outcome_type") or "").strip().lower()
    reliable_for_aggregation = _is_reliable_subtask_result(
        {
            "summary": run_result,
            "outcome_type": outcome_type,
        }
    )
    return {
        "id": subtask.id,
        "name": subtask.name,
        "list_url": subtask.list_url,
        "anchor_url": str(subtask.anchor_url or ""),
        "page_state_signature": str(subtask.page_state_signature or ""),
        "variant_label": str(subtask.variant_label or ""),
        "task_description": subtask.task_description,
        "mode": str(subtask.mode.value),
        "execution_brief": subtask.execution_brief.model_dump(mode="python"),
        "parent_id": str(subtask.parent_id or ""),
        "depth": int(subtask.depth or 0),
        "context": dict(subtask.context or {}),
        "status": status.value,
        "outcome_type": outcome_type,
        "error": error,
        "retry_count": int(subtask.retry_count or 0),
        "result_file": str(run_result.get("items_file") or subtask.result_file or ""),
        "collected_count": int(run_result.get("total_urls", 0) or subtask.collected_count or 0),
        "summary": {
            "total_urls": int(run_result.get("total_urls", 0) or 0),
            "success_count": int(run_result.get("success_count", 0) or 0),
            "failed_count": int(run_result.get("failed_count", 0) or 0),
            "success_rate": float(run_result.get("success_rate", 0.0) or 0.0),
            "required_field_success_rate": float(run_result.get("required_field_success_rate", 0.0) or 0.0),
            "validation_failure_count": int(run_result.get("validation_failure_count", 0) or 0),
            "execution_state": str(run_result.get("execution_state") or ""),
            "outcome_state": str(run_result.get("outcome_state") or ""),
            "terminal_reason": str(run_result.get("terminal_reason") or ""),
            "promotion_state": str(run_result.get("promotion_state") or ""),
            "execution_id": str(run_result.get("execution_id") or ""),
            "items_file": str(run_result.get("items_file") or ""),
            "durability_state": str(run_result.get("durability_state") or ""),
            "durably_persisted": bool(run_result.get("durably_persisted")),
            "reliable_for_aggregation": reliable_for_aggregation,
        },
        "collection_config": dict(run_result.get("collection_config") or {}),
        "extraction_config": dict(run_result.get("extraction_config") or {}),
        "extraction_evidence": list(run_result.get("extraction_evidence") or []),
        "validation_failures": list(run_result.get("validation_failures") or []),
        "journal_entries": list(run_result.get("journal_entries") or []),
        "expand_request": dict(expand_request or {}),
    }


def _apply_result_to_plan(plan: TaskPlan, result_item: dict[str, Any]) -> None:
    """提取子图并行返回状态更新并反向同步写回总 TaskPlan，更新原引用内的执行结果与采集量。"""
    subtask_id = str(result_item.get("id") or "")
    if not subtask_id:
        return
    for subtask in plan.subtasks:
        if subtask.id != subtask_id:
            continue
        status = str(result_item.get("status") or SubTaskStatus.SYSTEM_FAILURE.value)
        try:
            subtask.status = SubTaskStatus(status)
        except Exception:
            subtask.status = SubTaskStatus.SYSTEM_FAILURE
        subtask.error = str(result_item.get("error") or "") or None
        subtask.result_file = str(result_item.get("result_file") or "") or None
        subtask.collected_count = int(result_item.get("collected_count", 0) or 0)
        if result_item.get("task_description"):
            subtask.task_description = str(result_item.get("task_description") or "")
        if result_item.get("mode"):
            subtask.mode = SubTaskMode(str(result_item.get("mode") or SubTaskMode.COLLECT.value))
        if result_item.get("execution_brief"):
            subtask.execution_brief = ExecutionBrief.model_validate(result_item.get("execution_brief") or {})
        summary = dict(result_item.get("summary") or {})
        if summary:
            merged_context = dict(subtask.context or {})
            if "reliable_for_aggregation" in summary:
                merged_context["reliable_for_aggregation"] = bool(summary.get("reliable_for_aggregation"))
            if "durability_state" in summary:
                merged_context["durability_state"] = str(summary.get("durability_state") or "")
            if "durably_persisted" in summary:
                merged_context["durably_persisted"] = bool(summary.get("durably_persisted"))
            if "execution_id" in summary:
                merged_context["execution_id"] = str(summary.get("execution_id") or "")
            if result_item.get("outcome_type"):
                merged_context["outcome_type"] = str(result_item.get("outcome_type") or "")
            subtask.context = merged_context
        return


def _build_dispatch_summary(plan: TaskPlan, subtask_results: list[dict[str, Any]]) -> dict[str, Any]:
    """遍历统计任务树的状态，并生成全任务状态大盘报告（汇总每个状态的数量和采集总数），供全局决策。"""
    for item in subtask_results:
        _apply_result_to_plan(plan, item)

    total = len(plan.subtasks)
    completed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
    no_data = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.NO_DATA)
    expanded = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.EXPANDED)
    business_failure = sum(
        1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.BUSINESS_FAILURE
    )
    system_failure = sum(
        1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SYSTEM_FAILURE
    )
    skipped = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SKIPPED)
    total_collected = sum(
        int(subtask.collected_count or 0)
        for subtask in plan.subtasks
        if subtask.status == SubTaskStatus.COMPLETED
    )
    plan.total_subtasks = total
    if not plan.updated_at:
        plan.updated_at = plan.created_at
    return {
        "total": total,
        "completed": completed,
        "no_data": no_data,
        "expanded": expanded,
        "business_failure": business_failure,
        "system_failure": system_failure,
        "failed": business_failure + system_failure,
        "skipped": skipped,
        "total_collected": total_collected,
    }


def initialize_multi_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    """主调度初始化节点。验证任务 plan 对象并将待执行的初始子任务推入分发队列。"""
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法调度执行"},
            "error": {"code": "missing_task_plan", "message": "缺少任务计划，无法调度执行"},
        }

    queue = list(state.get("dispatch_queue") or [])
    if not queue:
        queue = [subtask.model_dump(mode="python") for subtask in plan.subtasks]

    return {
        "dispatch_queue": queue,
        "current_batch": list(state.get("current_batch") or []),
        "subtask_results": list(state.get("subtask_results") or []),
        "round_subtask_results": list(state.get("round_subtask_results") or []),
        "round_expand_requests": list(state.get("round_expand_requests") or []),
        "node_status": "ok",
        "node_error": None,
    }


def prepare_dispatch_batch(state: MultiDispatchState) -> MultiDispatchState:
    """提取排队中的任务，送入当前的并行执行批次 current_batch 并清理之前衍生的数据槽。"""
    queue = list(state.get("dispatch_queue") or [])
    batch_size = _resolve_dispatch_batch_size(state)
    return {
        "current_batch": queue[:batch_size],
        "dispatch_queue": queue[batch_size:],
        "round_subtask_results": [],
        "round_expand_requests": [],
    }


def route_dispatch_batch(state: MultiDispatchState):
    """采用 Send() API 执行任务的并行分散（Fan-out）。
    
    针对 current_batch 中的每个待运行子任务数据，通过 Send() 发送给名为 `execute_subtask_flow`
    的子图节点域中并行执行。如果队列为空则表示流转到 complete_dispatch。
    """
    batch = list(state.get("current_batch") or [])
    if not batch:
        return "complete_dispatch"

    params = dict(state.get("normalized_params") or {})
    plan = state.get("task_plan")
    # 将 thread_id 注入 params 中传递，避免子图并行写回时冲突
    params["_thread_id"] = str(state.get("thread_id") or "")
    return [
        Send(
            "execute_subtask_flow",
            {
                "normalized_params": params,
                "task_plan": plan,
                "plan_knowledge": str(state.get("plan_knowledge") or ""),
                "subtask_payload": payload,
            },
        )
        for payload in batch
    ]


async def run_subtask_worker_node(state: SubTaskFlowState):
    """(子任务态) 工作流执行节点。包裹了浏览器大模型爬虫 Worker 执行单一子任务逻辑。"""
    subtask = _restore_subtask(dict(state.get("subtask_payload") or {}))
    params = dict(state.get("normalized_params") or {})
    if subtask.max_pages is None and params.get("max_pages") is not None:
        subtask.max_pages = int(params["max_pages"])
    if subtask.target_url_count is None and params.get("target_url_count") is not None:
        subtask.target_url_count = int(params["target_url_count"])

    plan = state.get("task_plan")
    shared_fields = list(getattr(plan, "shared_fields", []) or [])
    plan_knowledge = str(state.get("plan_knowledge") or "")

    worker = SubTaskWorker(
        subtask=subtask,
        fields=shared_fields,
        output_dir=str(params.get("output_dir") or "output"),
        headless=params.get("headless"),
        thread_id=str(params.get("_thread_id") or ""),
        guard_intervention_mode="interrupt",
        consumer_concurrency=(
            int(params["consumer_concurrency"])
            if params.get("consumer_concurrency") is not None
            else None
        ),
        field_explore_count=(
            int(params["field_explore_count"])
            if params.get("field_explore_count") is not None
            else None
        ),
        field_validate_count=(
            int(params["field_validate_count"])
            if params.get("field_validate_count") is not None
            else None
        ),
        selected_skills=list(params.get("selected_skills") or []),
        plan_knowledge=plan_knowledge,
        task_plan_snapshot=plan.model_dump(mode="python") if isinstance(plan, TaskPlan) else {},
        plan_journal=[
            entry.model_dump(mode="python")
            for entry in list(getattr(plan, "journal", []) or [])
        ]
        if isinstance(plan, TaskPlan)
        else [],
        pipeline_mode=(
            PipelineMode(str(params.get("pipeline_mode") or "").strip().lower())
            if str(params.get("pipeline_mode") or "").strip()
            else None
        ),
    )
    while True:
        try:
            result = await worker.execute()
            break
        except BrowserInterventionRequired as exc:
            state["browser_resume"] = interrupt(exc.payload)
            continue

    effective_subtask = _restore_subtask(result.get("effective_subtask") or subtask.model_dump(mode="python"))
    expand_request = dict(result.get("expand_request") or {})

    status = _resolve_subtask_status(result)
    error = str(result.get("error") or "").strip()
    if not error and status == SubTaskStatus.SYSTEM_FAILURE:
        error = "subtask_result_not_durable"

    return {
        "subtask_result": _build_subtask_result(
            effective_subtask,
            status=status,
            error=error[:500],
            result=result,
            expand_request=expand_request,
        ),
        "round_expand_requests": [expand_request] if expand_request else [],
        "artifacts": [
            _artifact("subtask_items", result["items_file"])
            for _ in [1]
            if str(result.get("items_file") or "").strip()
        ],
    }




def finalize_subtask_flow(state: SubTaskFlowState) -> SubTaskFlowState:
    """(子任务态) 尾节点，收束整理产物供父节点调度器的 Reducer 执行吸收合并。"""
    result_item = dict(state.get("subtask_result") or {})
    updates: SubTaskFlowState = {
        "round_subtask_results": [result_item] if result_item else [],
        "round_expand_requests": list(state.get("round_expand_requests") or []),
    }
    artifacts = list(state.get("artifacts") or [])
    if artifacts:
        updates["artifacts"] = artifacts
    return updates


def merge_dispatch_round(state: MultiDispatchState) -> MultiDispatchState:
    """收集 (Fan-In) 并更新调度合并上一轮的执行情况，并将新衍生的子任务插入。"""
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法合并调度结果"},
            "error": {"code": "missing_task_plan", "message": "缺少任务计划，无法合并调度结果"},
        }

    round_result_items = list(state.get("round_subtask_results") or [])
    accumulated = list(state.get("subtask_results") or [])
    accumulated.extend(round_result_items)
    mutation_result = PlanMutationService().merge_expand_requests(
        plan=plan,
        expand_requests=list(state.get("round_expand_requests") or []),
        pending_queue=list(state.get("dispatch_queue") or []),
        output_dir=str(dict(state.get("normalized_params") or {}).get("output_dir") or "output"),
    )
    summary = _build_dispatch_summary(mutation_result.task_plan, accumulated)
    return {
        "task_plan": mutation_result.task_plan,
        "plan_knowledge": mutation_result.plan_knowledge,
        "dispatch_queue": list(mutation_result.dispatch_queue),
        "current_batch": [],
        "subtask_results": accumulated,
        "round_subtask_results": [],
        "round_expand_requests": [],
        "summary": summary,
        "dispatch": {
            "status": "ok",
            "task_plan": mutation_result.task_plan,
            "plan_knowledge": mutation_result.plan_knowledge,
            "summary": summary,
        },
    }


def route_after_merge(state: MultiDispatchState) -> str:
    """路由评估下一批并行或者直接结束整个调度子图。"""
    if str(state.get("node_status") or "ok") != "ok":
        return "error"
    if list(state.get("dispatch_queue") or []):
        return "dispatch_next_batch"
    return "complete_dispatch"


def complete_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    """完成整体调度。做最后的摘要汇总汇报以反馈给全局主图。"""
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法完成调度"},
            "error": {"code": "missing_task_plan", "message": "缺少任务计划，无法完成调度"},
        }

    result_items = list(state.get("subtask_results") or [])
    mutation_result = PlanMutationService().merge_expand_requests(
        plan=plan,
        expand_requests=[],
        pending_queue=list(state.get("dispatch_queue") or []),
        output_dir=str(dict(state.get("normalized_params") or {}).get("output_dir") or "output"),
    )
    summary = _build_dispatch_summary(mutation_result.task_plan, result_items)
    return {
        "task_plan": mutation_result.task_plan,
        "plan_knowledge": mutation_result.plan_knowledge,
        "dispatch_result": summary,
        "summary": summary,
        "node_status": "ok",
        "node_error": None,
        "node_payload": {"dispatch_result": summary},
        "dispatch": {
            "status": "ok",
            "task_plan": mutation_result.task_plan,
            "plan_knowledge": mutation_result.plan_knowledge,
            "dispatch_result": summary,
            "summary": summary,
        },
        "error": None,
    }


def build_multi_dispatch_subgraph():
    """编译并组装完整的执行分发子状态图。

    组合了单子任务的 StateGraph (SubTaskFlowState) 以及全局多任务分发的
    外部大 StateGraph (MultiDispatchState)。
    利用 Send API 的 ConditionalEdges 实现 MapReduce 的能力。
    """
    # 1. 内部独立执行单个子任务的小状态图
    subtask_flow = StateGraph(SubTaskFlowState)
    subtask_flow.add_node("run_subtask_worker", run_subtask_worker_node)
    subtask_flow.add_node("finalize_subtask_flow", finalize_subtask_flow)
    subtask_flow.set_entry_point("run_subtask_worker")
    subtask_flow.add_edge("run_subtask_worker", "finalize_subtask_flow")
    subtask_flow.add_edge("finalize_subtask_flow", END)

    # 2. 外部主调度引擎编排图
    builder = StateGraph(MultiDispatchState)
    builder.add_node("initialize_multi_dispatch", initialize_multi_dispatch)
    builder.add_node("prepare_dispatch_batch", prepare_dispatch_batch)
    builder.add_node("execute_subtask_flow", subtask_flow.compile())
    builder.add_node("merge_dispatch_round", merge_dispatch_round)
    builder.add_node("complete_dispatch", complete_dispatch)
    
    builder.set_entry_point("initialize_multi_dispatch")
    builder.add_edge("initialize_multi_dispatch", "prepare_dispatch_batch")
    
    # 将批量数据分配并散开进入独立的子图执行阶段
    builder.add_conditional_edges(
        "prepare_dispatch_batch",
        route_dispatch_batch,
        {"complete_dispatch": "complete_dispatch"},
    )
    
    builder.add_edge("execute_subtask_flow", "merge_dispatch_round")
    
    builder.add_conditional_edges(
        "merge_dispatch_round",
        route_after_merge,
        {
            "dispatch_next_batch": "prepare_dispatch_batch",
            "complete_dispatch": "complete_dispatch",
            "error": END,
        },
    )
    builder.add_edge("complete_dispatch", END)
    
    return builder.compile()
