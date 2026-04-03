from __future__ import annotations

import operator
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send, interrupt

from ...common.browser.intervention import BrowserInterventionRequired
from ...common.config import config
from ...domain.planning import SubTask, SubTaskStatus, TaskPlan
from ...pipeline.worker import SubTaskWorker


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
    dispatch_queue: list[dict[str, Any]]  # 尚未下发执行的子任务队列（等待进入下一批并行）
    current_batch: list[dict[str, Any]]  # 目前正被 Send API 分发在当前轮次被并行处理的一批子任务
    
    # 采用 operator.add 作为 Reducer，并行执行的多任务产生结果时自动合并 list，防止互相覆盖
    subtask_results: Annotated[list[dict[str, Any]], operator.add]  # 聚合每次并行工作流返回的执行结果记录
    spawned_subtasks: Annotated[list[dict[str, Any]], operator.add]  # 聚合执行中途泛化拆分出来的新派生任务
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
    subtask_payload: dict[str, Any]  # 被分配到当前分片节点运行的目标子任务配置字典
    subtask_result: dict[str, Any]   # 记录当前单独这个子任务完成后的成功与否及提取数量等结果信息
    
    # 类似上层，利用 operator.add 支持在流中合并多次步骤生成的产物（例如被重新规划出多个）
    spawned_subtasks: Annotated[list[dict[str, Any]], operator.add]  # 如果本任务申请细化分拆，此处存放新生成的孩子任务
    subtask_results: Annotated[list[dict[str, Any]], operator.add]  # 向下个 finalize 节点投递结果（兼容合并）
    artifacts: Annotated[list[dict[str, str]], operator.add]  # 该子任务保存到本地结果等记录的制品文件信息

def _artifact(label: str, path: str | Path) -> dict[str, str]:
    """快捷构造标准附件制品的字典记录。"""
    return {"label": label, "path": str(path)}


def _subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str]:
    """生成子任务唯一特征指纹用于排重（name + url + task_description）。"""
    return (
        str(payload.get("name") or "").strip(),
        str(payload.get("list_url") or "").strip(),
        str(payload.get("task_description") or "").strip(),
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
    default_value = int(getattr(config.planner, "runtime_subtasks_max_children", 1) or 1)
    raw_value = params.get("runtime_subtask_max_children")
    try:
        resolved = int(raw_value) if raw_value is not None else default_value
    except (TypeError, ValueError):
        resolved = default_value
    return max(1, resolved)


def _resolve_runtime_subtasks_use_main_model(params: dict[str, Any]) -> bool:
    default_value = bool(getattr(config.planner, "runtime_subtasks_use_main_model", False))
    raw_value = params.get("runtime_subtasks_use_main_model")
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off", ""}


def _resolve_dispatch_batch_size(state: MultiDispatchState) -> int:
    params = dict(state.get("normalized_params") or {})
    raw_value = params.get("max_concurrent")
    try:
        batch_size = int(raw_value) if raw_value is not None else config.planner.max_concurrent_subtasks
    except (TypeError, ValueError):
        batch_size = config.planner.max_concurrent_subtasks
    return max(1, batch_size)




def _build_subtask_result(
    subtask: SubTask,
    *,
    status: SubTaskStatus,
    error: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """标准化构建包含运行状态及其结果文件等核心指标的子任务结果字典。"""
    run_result = dict(result or {})
    return {
        "id": subtask.id,
        "name": subtask.name,
        "list_url": subtask.list_url,
        "task_description": subtask.task_description,
        "status": status.value,
        "error": error,
        "retry_count": int(subtask.retry_count or 0),
        "result_file": str(run_result.get("items_file") or subtask.result_file or ""),
        "collected_count": int(run_result.get("total_urls", 0) or subtask.collected_count or 0),
    }


def _apply_result_to_plan(plan: TaskPlan, result_item: dict[str, Any]) -> None:
    """提取子图并行返回状态更新并反向同步写回总 TaskPlan，更新原引用内的执行结果与采集量。"""
    subtask_id = str(result_item.get("id") or "")
    if not subtask_id:
        return
    for subtask in plan.subtasks:
        if subtask.id != subtask_id:
            continue
        status = str(result_item.get("status") or SubTaskStatus.FAILED.value)
        try:
            subtask.status = SubTaskStatus(status)
        except Exception:
            subtask.status = SubTaskStatus.FAILED
        subtask.error = str(result_item.get("error") or "") or None
        subtask.result_file = str(result_item.get("result_file") or "") or None
        subtask.collected_count = int(result_item.get("collected_count", 0) or 0)
        return


def _build_dispatch_summary(plan: TaskPlan, subtask_results: list[dict[str, Any]]) -> dict[str, Any]:
    """遍历统计任务树的状态，并生成全任务状态大盘报告（汇总每个状态的数量和采集总数），供全局决策。"""
    for item in subtask_results:
        _apply_result_to_plan(plan, item)

    total = len(plan.subtasks)
    completed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
    failed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.FAILED)
    skipped = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SKIPPED)
    total_collected = sum(int(subtask.collected_count or 0) for subtask in plan.subtasks)
    plan.total_subtasks = total
    if not plan.updated_at:
        plan.updated_at = plan.created_at
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
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
        }

    queue = list(state.get("dispatch_queue") or [])
    if not queue:
        queue = [subtask.model_dump(mode="python") for subtask in plan.subtasks]

    return {
        "dispatch_queue": queue,
        "current_batch": list(state.get("current_batch") or []),
        "subtask_results": list(state.get("subtask_results") or []),
        "spawned_subtasks": list(state.get("spawned_subtasks") or []),
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
        "spawned_subtasks": [],
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

    try:
        worker = SubTaskWorker(
            subtask=subtask,
            fields=shared_fields,
            output_dir=str(params.get("output_dir") or "output"),
            headless=bool(params.get("headless", False)),
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
        )
        result = await worker.execute()
    except BrowserInterventionRequired as exc:
        interrupt(exc.payload)
        return await run_subtask_worker_node(state)
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc), "items_file": "", "total_urls": 0}


    pipeline_error = str(result.get("error") or "").strip()
    if pipeline_error:
        status = SubTaskStatus.FAILED
        error = pipeline_error[:500]
    elif int(result.get("total_urls", 0) or 0) <= 0:
        status = SubTaskStatus.FAILED
        error = "no_data_collected"
    else:
        status = SubTaskStatus.COMPLETED
        error = ""

    return {
        "subtask_result": _build_subtask_result(subtask, status=status, error=error, result=result),
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
        "subtask_results": [result_item] if result_item else [],
        "spawned_subtasks": list(state.get("spawned_subtasks") or []),
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
        }

    known = {_subtask_signature(subtask.model_dump(mode="python")) for subtask in plan.subtasks}
    queue: list[dict[str, Any]] = []
    for payload in list(state.get("spawned_subtasks") or []):
        payload = _inherit_parent_nav_steps(payload, plan)
        signature = _subtask_signature(payload)
        if signature in known:
            continue
        known.add(signature)
        plan.subtasks.append(_restore_subtask(payload))
        queue.append(payload)

    summary = _build_dispatch_summary(plan, list(state.get("subtask_results") or []))
    return {
        "task_plan": plan,
        "dispatch_queue": queue,
        "current_batch": [],
        "spawned_subtasks": [],
        "summary": summary,
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
        }

    summary = _build_dispatch_summary(plan, list(state.get("subtask_results") or []))
    return {
        "task_plan": plan,
        "dispatch_result": summary,
        "summary": summary,
        "node_status": "ok",
        "node_error": None,
        "node_payload": {"dispatch_result": summary},
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
