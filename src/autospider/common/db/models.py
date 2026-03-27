"""SQLAlchemy ORM 模型定义。

所有跨模块共享的持久化实体在此定义，作为数据库 schema 的唯一事实来源。

层级关系：
    tasks  →  task_executions  →  subtasks  →  collected_urls / extracted_items
    （定义）    （每次运行）      （子任务）      （URL / 提取结果）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


# ============================================================================
# 任务定义（长期存在，按 URL+描述 去重）
# ============================================================================


class TaskRecord(Base):
    """任务定义 — 按 (normalized_url, task_description) 唯一。

    同一个 URL 的同一个采集意图只有一条记录，
    每次执行的详情记录在 task_executions 表中。
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    registry_id = Column(String(16), nullable=False, comment="hash(normalized_url:task_description)")
    normalized_url = Column(Text, nullable=False, index=True, comment="归一化 URL")
    original_url = Column(Text, nullable=False, comment="原始 URL")
    task_description = Column(Text, nullable=False, comment="任务描述")
    fields = Column(JSONB, default=list, comment="提取字段名称列表")
    created_at = Column(DateTime, default=datetime.now, comment="首次创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="最后更新时间")

    # 关联
    executions = relationship("TaskExecution", back_populates="task", cascade="all, delete-orphan",
                              order_by="TaskExecution.started_at.desc()")
    configs = relationship("TaskConfig", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tasks_norm_url_desc", "normalized_url", "task_description", unique=True),
    )

    @property
    def latest_execution(self) -> "TaskExecution | None":
        """获取最近一次执行记录。"""
        return self.executions[0] if self.executions else None

    def to_dict(self) -> dict:
        """转换为与旧 TaskRegistry JSON 格式兼容的字典。

        为了兼容性，从最近一次执行中提取 execution_id / status / collected_count 等字段。
        """
        latest = self.latest_execution
        return {
            "registry_id": self.registry_id,
            "normalized_url": self.normalized_url,
            "original_url": self.original_url,
            "task_description": self.task_description,
            "fields": list(self.fields or []),
            "execution_id": latest.execution_id if latest else "",
            "output_dir": latest.output_dir if latest else "",
            "status": latest.status if latest else "",
            "collected_count": latest.collected_count if latest else 0,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


# ============================================================================
# 执行历史（每次运行一条，不覆盖）
# ============================================================================


class TaskExecution(Base):
    """任务执行历史 — 每次运行都会创建一条新记录，永不覆盖。

    同一个 task 可以执行多次，每次的参数、结果、耗时都独立保存。
    """

    __tablename__ = "task_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_id = Column(String(64), nullable=False, unique=True, index=True, comment="执行 ID (hash)")
    output_dir = Column(String(512), default="", comment="输出目录")
    status = Column(String(20), default="running", comment="running/completed/failed")
    collected_count = Column(Integer, default=0, comment="已采集数量")
    fields = Column(JSONB, default=list, comment="本次执行使用的字段定义")
    config_snapshot = Column(JSONB, default=dict, comment="本次执行的运行参数快照")
    error = Column(Text, nullable=True, comment="错误信息")
    started_at = Column(DateTime, default=datetime.now, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    task = relationship("TaskRecord", back_populates="executions")
    subtasks = relationship("SubTaskRecord", back_populates="execution", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "status": self.status or "",
            "collected_count": self.collected_count or 0,
            "output_dir": self.output_dir or "",
            "fields": list(self.fields or []),
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
        }


# ============================================================================
# 子任务（挂在执行记录下）
# ============================================================================


class SubTaskRecord(Base):
    """子任务记录 — 对应 TaskPlan 中的 SubTask。

    归属于某次具体的执行（task_execution），而非任务定义。
    """

    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subtask_id = Column(String(64), nullable=False, index=True, comment="子任务 ID (如 category_01)")
    execution_id = Column(Integer, ForeignKey("task_executions.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False, comment="子任务名称")
    list_url = Column(Text, nullable=False, comment="列表页 URL")
    task_description = Column(Text, default="", comment="任务描述")
    status = Column(String(20), default="pending", comment="状态")
    fields = Column(JSONB, default=list, comment="字段定义 JSON")
    nav_steps = Column(JSONB, default=list, comment="导航步骤")
    max_pages = Column(Integer, nullable=True, comment="最大翻页次数")
    target_url_count = Column(Integer, nullable=True, comment="目标 URL 数量")
    priority = Column(Integer, default=0, comment="优先级")
    parent_id = Column(String(64), nullable=True, comment="父子任务 ID")
    depth = Column(Integer, default=0, comment="任务层级")
    collected_count = Column(Integer, default=0, comment="已采集数量")
    error = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    execution = relationship("TaskExecution", back_populates="subtasks")
    collected_urls = relationship("CollectedURL", back_populates="subtask", cascade="all, delete-orphan")
    extracted_items = relationship("ExtractedItem", back_populates="subtask", cascade="all, delete-orphan")


# ============================================================================
# URL 收集记录
# ============================================================================


class CollectedURL(Base):
    """已收集的 URL 记录。"""

    __tablename__ = "collected_urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subtask_id = Column(Integer, ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    status = Column(String(20), default="pending", comment="pending/processing/completed/failed")
    failure_reason = Column(Text, nullable=True, comment="失败原因")
    retry_count = Column(Integer, default=0, comment="重试次数")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    subtask = relationship("SubTaskRecord", back_populates="collected_urls")

    __table_args__ = (
        Index("ix_collected_urls_subtask_url", "subtask_id", "url", unique=True),
    )


# ============================================================================
# 提取结果
# ============================================================================


class ExtractedItem(Base):
    """字段提取结果记录。"""

    __tablename__ = "extracted_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subtask_id = Column(Integer, ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(Text, nullable=False, index=True, comment="详情页 URL")
    success = Column(Boolean, default=False, comment="提取是否成功")
    data = Column(JSONB, default=dict, comment="提取到的字段数据")
    error = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    subtask = relationship("SubTaskRecord", back_populates="extracted_items")

    __table_args__ = (
        Index("ix_extracted_items_data_gin", "data", postgresql_using="gin"),
    )


# ============================================================================
# 任务配置快照
# ============================================================================


class TaskConfig(Base):
    """任务运行配置快照（collection_config / extraction_config / progress 等）。"""

    __tablename__ = "task_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    config_type = Column(String(64), nullable=False, comment="配置类型")
    config_data = Column(JSONB, default=dict, comment="配置 JSON 数据")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    task = relationship("TaskRecord", back_populates="configs")

    __table_args__ = (
        Index("ix_task_configs_task_type", "task_id", "config_type"),
    )
