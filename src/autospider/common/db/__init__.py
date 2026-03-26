"""数据库模块。

提供 SQLAlchemy ORM 引擎管理、模型定义和 Repository 数据访问层。
通过 DB_ENABLED 环境变量控制是否启用。
"""

from __future__ import annotations

from .engine import get_engine, get_session, init_db
from .models import Base, TaskRecord, TaskExecution, SubTaskRecord, CollectedURL, ExtractedItem, TaskConfig

__all__ = [
    "get_engine",
    "get_session",
    "init_db",
    "Base",
    "TaskRecord",
    "TaskExecution",
    "SubTaskRecord",
    "CollectedURL",
    "ExtractedItem",
    "TaskConfig",
]
