"""规划与调度领域模型。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SubTaskStatus(str, Enum):
    """子任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SubTask(BaseModel):
    """单个子任务定义。"""

    id: str = Field(..., description="唯一标识 (如 category_01)")
    name: str = Field(..., description="人类可读名称 (如 招标公告)")
    list_url: str = Field(..., description="该子任务的列表页 URL")
    task_description: str = Field(..., description="给 LLM 的任务描述")
    fields: list[dict] = Field(default_factory=list, description="字段定义 (可继承父任务)")
    max_pages: int | None = Field(default=None, description="最大翻页次数")
    target_url_count: int | None = Field(default=None, description="目标采集 URL 数量")
    priority: int = Field(default=0, description="优先级，越小越优先")
    parent_id: str | None = Field(default=None, description="父子任务 ID（运行时拆分时使用）")
    depth: int = Field(default=0, description="子任务层级深度（根任务=0）")
    nav_steps: list[dict] = Field(default_factory=list, description="从首页到达该分类的导航步骤")
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
    total_subtasks: int = Field(default=0, description="子任务总数")
    shared_fields: list[dict] = Field(default_factory=list, description="所有子任务共享的字段定义")
    created_at: str = Field(default="", description="创建时间")
    updated_at: str = Field(default="", description="最后更新时间")
