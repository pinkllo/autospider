"""现版本 PostgreSQL 持久化模型。

数据库层现在承担主持久化职责：
- `tasks` 保存可复用任务定义，按 `(normalized_url, page_state_signature, task_description)` 唯一。
- `task_runs` 保存每次运行的完整快照与摘要。
- `task_run_items` 保存每个 URL 的最终提取结果。
- `task_run_validation_failures` 保存探索阶段的校验失败明细。
- `field_xpaths` 保存详情页字段的已验证完整 XPath 统计。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class TaskRecord(Base):
    """可复用任务定义。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registry_id: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    page_state_signature: Mapped[str] = mapped_column(Text, default="", nullable=False)
    anchor_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    variant_label: Mapped[str] = mapped_column(Text, default="", nullable=False)
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    field_names: Mapped[list[str]] = mapped_column(JSON_VALUE, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )

    runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="desc(TaskRun.started_at)",
    )

    __table_args__ = (
        Index(
            "ix_tasks_norm_state_desc",
            "normalized_url",
            "page_state_signature",
            "task_description",
            unique=True,
        ),
    )

    @property
    def latest_run(self) -> "TaskRun | None":
        return self.runs[0] if self.runs else None

    @property
    def latest_reusable_run(self) -> "TaskRun | None":
        for run in self.runs:
            if run.promotion_state == "reusable":
                return run
        return None

    def to_registry_dict(self, run: "TaskRun") -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "normalized_url": self.normalized_url,
            "original_url": self.original_url,
            "page_state_signature": self.page_state_signature,
            "anchor_url": self.anchor_url,
            "variant_label": self.variant_label,
            "task_description": self.task_description,
            "fields": list(self.field_names or []),
            "execution_id": run.execution_id,
            "output_dir": run.output_dir or "",
            "status": run.execution_state or "",
            "collected_count": run.total_urls or 0,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class TaskRun(Base):
    """单次运行的完整快照。"""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), default="")
    output_dir: Mapped[str] = mapped_column(String(512), default="")
    pipeline_mode: Mapped[str] = mapped_column(String(20), default="")
    execution_state: Mapped[str] = mapped_column(String(20), default="running")
    outcome_state: Mapped[str] = mapped_column(String(32), default="")
    promotion_state: Mapped[str] = mapped_column(String(32), default="")
    total_urls: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(default=0.0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    collection_config: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    extraction_config: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    plan_knowledge: Mapped[str] = mapped_column(Text, default="")
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    plan_journal: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )

    task: Mapped[TaskRecord] = relationship(back_populates="runs")
    items: Mapped[list["TaskRunItem"]] = relationship(
        back_populates="task_run",
        cascade="all, delete-orphan",
        order_by="TaskRunItem.id",
    )
    validation_failures: Mapped[list["TaskRunValidationFailure"]] = relationship(
        back_populates="task_run",
        cascade="all, delete-orphan",
        order_by="TaskRunValidationFailure.id",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "output_dir": self.output_dir,
            "pipeline_mode": self.pipeline_mode,
            "execution_state": self.execution_state,
            "outcome_state": self.outcome_state,
            "promotion_state": self.promotion_state,
            "total_urls": self.total_urls,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "validation_failure_count": self.validation_failure_count,
            "success_rate": self.success_rate,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
        }


class TaskRunItem(Base):
    """单次运行中每个 URL 的最终结果。"""

    __tablename__ = "task_run_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    item_data: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    task_run: Mapped[TaskRun] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_task_run_items_run_url", "task_run_id", "url", unique=True),
    )


class TaskRunValidationFailure(Base):
    """单次运行中的校验失败明细。"""

    __tablename__ = "task_run_validation_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, default="")
    failure_data: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    task_run: Mapped[TaskRun] = relationship(back_populates="validation_failures")


class FieldXPath(Base):
    """详情页字段 XPath 统计。"""

    __tablename__ = "field_xpaths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    xpath: Mapped[str] = mapped_column(Text, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )

    __table_args__ = (
        Index("ix_field_xpaths_domain_field_xpath", "domain", "field_name", "xpath", unique=True),
    )
