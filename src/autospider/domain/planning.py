"""规划与调度领域模型。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SubTaskStatus(str, Enum):
    """子任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    EXPANDED = "expanded"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SubTaskMode(str, Enum):
    """子任务执行模式。"""

    EXPAND = "expand"
    COLLECT = "collect"


class PlanNodeType(str, Enum):
    """计划树节点类型。"""

    ROOT = "root"
    CATEGORY = "category"
    LIST_PAGE = "list_page"
    STATEFUL_LIST = "stateful_list"
    LEAF = "leaf"


class PlanNode(BaseModel):
    """结构化计划节点。"""

    node_id: str = Field(..., description="节点唯一 ID")
    parent_node_id: str | None = Field(default=None, description="父节点 ID")
    name: str = Field(..., description="节点名称")
    node_type: PlanNodeType = Field(..., description="节点类型")
    url: str = Field(default="", description="节点对应 URL")
    anchor_url: str | None = Field(default=None, description="节点恢复执行时使用的锚点 URL")
    page_state_signature: str | None = Field(default=None, description="节点页面状态签名")
    variant_label: str | None = Field(default=None, description="同页状态变体标签")
    task_description: str = Field(default="", description="节点任务描述")
    observations: str = Field(default="", description="LLM 对该节点的观察")
    depth: int = Field(default=0, description="节点深度")
    nav_steps: list[dict] = Field(default_factory=list, description="到达该节点的导航链")
    context: dict[str, str] = Field(default_factory=dict, description="节点上下文字典")
    subtask_id: str | None = Field(default=None, description="若是可执行叶子，对应的子任务 ID")
    is_leaf: bool = Field(default=False, description="是否叶子节点")
    executable: bool = Field(default=False, description="是否可直接执行")
    children_count: int = Field(default=0, description="子节点数")


class PlanJournalEntry(BaseModel):
    """计划变更与执行原因日志。"""

    entry_id: str = Field(..., description="日志唯一 ID")
    node_id: str | None = Field(default=None, description="关联节点 ID")
    phase: str = Field(default="", description="阶段，例如 planning/pipeline")
    action: str = Field(default="", description="动作类型")
    reason: str = Field(default="", description="动作原因")
    evidence: str = Field(default="", description="动作依据")
    metadata: dict[str, str] = Field(default_factory=dict, description="补充结构化元信息")
    created_at: str = Field(default="", description="记录时间")


class ExecutionBrief(BaseModel):
    """子任务执行简报。"""

    parent_chain: list[str] = Field(default_factory=list, description="父链路名称列表")
    current_scope: str = Field(default="", description="当前任务作用域")
    objective: str = Field(default="", description="当前任务目标")
    next_action: str = Field(default="", description="下一步优先动作")
    stop_rule: str = Field(default="", description="停止扩树并开始采集的条件")
    do_not: list[str] = Field(default_factory=list, description="当前层禁止事项")


class SubTask(BaseModel):
    """单个子任务定义。"""

    id: str = Field(..., description="唯一标识 (如 category_01)")
    name: str = Field(..., description="人类可读名称 (如 招标公告)")
    list_url: str = Field(..., description="该子任务的列表页或执行入口 URL")
    anchor_url: str | None = Field(default=None, description="恢复该状态时使用的锚点 URL")
    page_state_signature: str = Field(default="", description="该子任务唯一页面状态签名")
    variant_label: str | None = Field(default=None, description="同页状态变体标签")
    task_description: str = Field(..., description="给 LLM 的任务描述")
    fields: list[dict] = Field(default_factory=list, description="字段定义 (可继承父任务)")
    max_pages: int | None = Field(default=None, description="最大翻页次数")
    target_url_count: int | None = Field(default=None, description="目标采集 URL 数量")
    priority: int = Field(default=0, description="优先级，越小越优先")
    parent_id: str | None = Field(default=None, description="父子任务 ID（运行时拆分时使用）")
    depth: int = Field(default=0, description="子任务层级深度（根任务=0）")
    nav_steps: list[dict] = Field(default_factory=list, description="从首页到达该分类的导航步骤")
    context: dict[str, str] = Field(default_factory=dict, description="显式上下文，例如所属分类")
    mode: SubTaskMode = Field(default=SubTaskMode.COLLECT, description="运行模式")
    execution_brief: ExecutionBrief = Field(default_factory=ExecutionBrief, description="结构化执行简报")
    plan_node_id: str | None = Field(default=None, description="关联的计划节点 ID")
    status: SubTaskStatus = Field(default=SubTaskStatus.PENDING, description="当前状态")
    retry_count: int = Field(default=0, description="已重试次数")
    error: str | None = Field(default=None, description="最近一次错误信息")
    result_file: str | None = Field(default=None, description="该子任务的结果文件路径")
    collected_count: int = Field(default=0, description="已采集数量")


class TaskPlan(BaseModel):
    """任务执行计划。"""

    plan_id: str = Field(..., description="计划唯一 ID")
    original_request: str = Field(..., description="原始用户需求")
    site_url: str = Field(..., description="目标网站 URL")
    subtasks: list[SubTask] = Field(default_factory=list, description="子任务列表")
    nodes: list[PlanNode] = Field(default_factory=list, description="结构化计划树节点")
    journal: list[PlanJournalEntry] = Field(default_factory=list, description="计划与执行日志")
    total_subtasks: int = Field(default=0, description="子任务总数")
    shared_fields: list[dict] = Field(default_factory=list, description="所有子任务共享的字段定义")
    created_at: str = Field(default="", description="创建时间")
    updated_at: str = Field(default="", description="最后更新时间")


def format_execution_brief(brief: ExecutionBrief | dict | None) -> str:
    """将结构化执行简报转成适合喂给 prompt 的文本。"""
    if brief is None:
        return "无"
    if isinstance(brief, dict):
        brief = ExecutionBrief.model_validate(brief)

    parts: list[str] = []
    if brief.parent_chain:
        parts.append(f"- 父链路: {' > '.join(brief.parent_chain)}")
    if brief.current_scope:
        parts.append(f"- 当前作用域: {brief.current_scope}")
    if brief.objective:
        parts.append(f"- 目标: {brief.objective}")
    if brief.next_action:
        parts.append(f"- 下一步: {brief.next_action}")
    if brief.stop_rule:
        parts.append(f"- 停止条件: {brief.stop_rule}")
    for item in list(brief.do_not or []):
        text = str(item or "").strip()
        if text:
            parts.append(f"- 禁止: {text}")
    return "\n".join(parts) if parts else "无"
