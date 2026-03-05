"""
MainGraph：单图多入口编排。
该模块负责构建整个自适应爬虫的主状态图（Main Graph），管理不同模式（如聊天、单页抓取、多页抓取等）下的状态流转与节点执行。
基于 LangGraph 实现，通过单一的入口根据 entry_mode 进行路由分发。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.capability_nodes import (
    aggregate_node,
    batch_collect_node,
    collect_urls_node,
    dispatch_node,
    execute_single_or_multi,
    field_extract_node,
    generate_config_node,
    plan_node,
    run_pipeline_node,
)
from .nodes.entry_nodes import (
    chat_clarify,
    chat_route_execution,
    normalize_pipeline_params,
    route_entry,
)
from .nodes.shared_nodes import build_artifact_index, build_summary, finalize_result
from .state import GraphState


def resolve_entry_route(state: dict[str, Any]) -> str:
    """
    根据 entry_mode（入口模式）返回下一个需要执行的节点名。
    此函数作为条件边的路由逻辑，决定状态图的初始分支走向。
    
    参数:
        state: 当前的图状态字典
        
    返回:
        str: 下一个被执行的节点名称
    """
    # 模式到对应入口图节点的映射表
    mapping = {
        "chat_pipeline": "chat_clarify",               # 聊天模式：先进行需求澄清与对话交互
        "pipeline_run": "normalize_pipeline_params",   # 单页面执行模式：直接执行单任务的流水线参数归一化
        "collect_urls": "collect_urls_node",           # URL收集模式：单独拉取和搜集待抓取的链接
        "generate_config": "generate_config_node",     # 配置生成模式：基于链接或需求自动生成抓取配置
        "batch_collect": "batch_collect_node",         # 批量收集模式：依据生成的配置批量抓取多个页面
        "field_extract": "field_extract_node",         # 字段提取模式：直接从页面数据中提取结构化字段
        "multi_pipeline": "plan_node",                 # 多任务流水线模式：进行任务规划，递归分解子任务
    }
    
    # 获取当前的入口执行模式，如果不存在则使用空字符串
    mode = str(state.get("entry_mode") or "")
    
    # 如果给定的模式不在预定义的映射表中，将统一走向收尾节点，结束流程
    if mode not in mapping:
        return "finalize_result"
        
    return mapping[mode]


def resolve_node_outcome(state: dict[str, Any]) -> str:
    """
    根据 node_status（节点执行状态）选择图是继续向下执行还是走向收尾阶段。
    通常用于判定当前节点是否执行成功，成功则继续处理流（返回 "ok"），失败则进入后续或收尾处理（返回 "error"）。
    
    参数:
        state: 当前的图状态字典
        
    返回:
        str: 状态结果 "ok" 或 "error"
    """
    if str(state.get("node_status") or "") == "ok":
        return "ok"
    return "error"


def build_main_graph():
    """
    构建并编译主图（Main Graph）。
    此函数将所有相关的能力节点、入口节点和共享收尾节点注册到图上，并定义了节点之间的有向连接边及条件选择边。
    
    返回:
        CompiledGraph: 编译好可直接运行的 LangGraph 实例
    """
    graph = StateGraph(GraphState)

    # ==============================
    # 1. 节点注册阶段
    # 将所有的业务处理节点加入状态图中
    # ==============================
    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_route_execution", chat_route_execution)
    graph.add_node("execute_single_or_multi", execute_single_or_multi)
    graph.add_node("normalize_pipeline_params", normalize_pipeline_params)
    graph.add_node("run_pipeline_node", run_pipeline_node)
    graph.add_node("collect_urls_node", collect_urls_node)
    graph.add_node("generate_config_node", generate_config_node)
    graph.add_node("batch_collect_node", batch_collect_node)
    graph.add_node("field_extract_node", field_extract_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("dispatch_node", dispatch_node)
    graph.add_node("aggregate_node", aggregate_node)
    graph.add_node("build_artifact_index", build_artifact_index)
    graph.add_node("build_summary", build_summary)
    graph.add_node("finalize_result", finalize_result)

    # ==============================
    # 2. 从入口开始的路由逻辑
    # 指定起点，并根据模式进入具体的处理分支
    # ==============================
    graph.set_entry_point("route_entry")
    graph.add_conditional_edges(
        "route_entry",
        resolve_entry_route,
        {
            "chat_clarify": "chat_clarify",                            # 聊天澄清分支
            "normalize_pipeline_params": "normalize_pipeline_params",  # 管道参数归一化分支
            "collect_urls_node": "collect_urls_node",                  # URL收集分支
            "generate_config_node": "generate_config_node",            # 配置生成分支
            "batch_collect_node": "batch_collect_node",                # 批量收集分支
            "field_extract_node": "field_extract_node",                # 自动字段提取分支
            "plan_node": "plan_node",                                  # 多任务规划分支
            "finalize_result": "finalize_result",                      # 未知状态直接结单
        },
    )

    # ==============================
    # 3. 聊天与执行分支路线
    # 确认需求后交由专门方法进行执行编排
    # ==============================
    graph.add_conditional_edges(
        "chat_clarify",
        resolve_node_outcome,
        {"ok": "chat_route_execution", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "chat_route_execution",
        resolve_node_outcome,
        {"ok": "execute_single_or_multi", "error": "build_artifact_index"},
    )
    graph.add_edge("execute_single_or_multi", "build_artifact_index")

    # ==============================
    # 4. 单流管道(Pipeline)执行路线
    # ==============================
    graph.add_conditional_edges(
        "normalize_pipeline_params",
        resolve_node_outcome,
        {"ok": "run_pipeline_node", "error": "build_artifact_index"},
    )
    graph.add_edge("run_pipeline_node", "build_artifact_index")

    # ==============================
    # 5. 各项基础能力节点单步调用路线
    # ==============================
    graph.add_edge("collect_urls_node", "build_artifact_index")
    graph.add_edge("generate_config_node", "build_artifact_index")
    graph.add_edge("batch_collect_node", "build_artifact_index")
    graph.add_edge("field_extract_node", "build_artifact_index")

    # ==============================
    # 6. 多任务规划与分发路线
    # (典型的基于"规划与执行"模式的多 Agent 协作)
    # ==============================
    graph.add_conditional_edges(
        "plan_node",
        resolve_node_outcome,
        {"ok": "dispatch_node", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "dispatch_node",
        resolve_node_outcome,
        {"ok": "aggregate_node", "error": "build_artifact_index"},
    )
    graph.add_edge("aggregate_node", "build_artifact_index")

    # ==============================
    # 7. 共享收尾整理阶段
    # 处理构建工件的索引，最后进行输出的终结
    # ==============================
    graph.add_edge("build_artifact_index", "build_summary")
    graph.add_edge("build_summary", "finalize_result")
    graph.add_edge("finalize_result", END)

    # 编译并返回构建好的 LangGraph 对象
    return graph.compile()
