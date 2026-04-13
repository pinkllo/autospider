"""数据库引擎管理。

负责 SQLAlchemy Engine / Session 的生命周期管理，
支持通过 DATABASE_URL 切换 PostgreSQL / SQLite / MySQL 等后端。
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import MetaData, Table, create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from autospider.common.config import config
from autospider.common.logger import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _normalize_database_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return text
    parsed = urlsplit(text)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme != "postgresql":
        return text
    return urlunsplit(("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


_LEGACY_TABLES = [
    "field_xpaths",
    "task_run_validation_failures",
    "task_run_items",
    "task_runs",
    "task_configs",
    "extracted_items",
    "collected_urls",
    "subtasks",
    "task_executions",
    "tasks",
]
_EXPECTED_COLUMNS = {
    "tasks": {
        "id",
        "registry_id",
        "normalized_url",
        "original_url",
        "page_state_signature",
        "anchor_url",
        "variant_label",
        "task_description",
        "field_names",
        "created_at",
        "updated_at",
    },
    "task_runs": {
        "id",
        "task_id",
        "execution_id",
        "thread_id",
        "output_dir",
        "pipeline_mode",
        "execution_state",
        "outcome_state",
        "promotion_state",
        "total_urls",
        "success_count",
        "failed_count",
        "validation_failure_count",
        "success_rate",
        "error_message",
        "summary_json",
        "collection_config",
        "extraction_config",
        "plan_knowledge",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    },
    "task_run_items": {
        "id",
        "task_run_id",
        "url",
        "claim_state",
        "durability_state",
        "terminal_reason",
        "error_kind",
        "attempt_count",
        "worker_id",
        "success",
        "failure_reason",
        "item_data",
        "claimed_at",
        "durably_committed_at",
        "acked_at",
        "created_at",
        "updated_at",
    },
    "task_run_validation_failures": {
        "id",
        "task_run_id",
        "url",
        "failure_data",
        "created_at",
    },
    "field_xpaths": {
        "id",
        "domain",
        "field_name",
        "xpath",
        "success_count",
        "failure_count",
        "last_success_at",
        "last_failure_at",
        "created_at",
        "updated_at",
    },
}


def get_engine() -> Engine:
    """获取或创建全局数据库引擎（单例）。"""
    global _engine
    if _engine is not None:
        return _engine

    db_config = config.database
    url = _normalize_database_url(db_config.url)

    engine_kwargs: dict = {
        "echo": db_config.echo,
        "pool_pre_ping": True,
    }

    # SQLite 不支持连接池参数
    if not url.startswith("sqlite"):
        engine_kwargs["pool_size"] = db_config.pool_size
        engine_kwargs["max_overflow"] = db_config.max_overflow
    else:
        # SQLite WAL 模式提升并发读性能
        @event.listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    _engine = create_engine(url, **engine_kwargs)
    logger.info("[DB] 引擎已创建: %s", url.split("@")[-1] if "@" in url else url)
    return _engine


def get_session() -> Session:
    """创建一个新的数据库 Session。

    调用方负责 commit / rollback / close。
    推荐使用 session_scope() 上下文管理器代替。
    """
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """提供一个围绕一系列操作的事务性 Session 作用域。

    用法::

        with session_scope() as session:
            session.add(record)
            # 退出时自动 commit，异常时自动 rollback
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _drop_known_tables(engine: Engine) -> None:
    dialect = engine.dialect.name.lower()
    with engine.begin() as connection:
        for table_name in _LEGACY_TABLES:
            if dialect == "postgresql":
                connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
                connection.execute(text(f'DROP SEQUENCE IF EXISTS "{table_name}_id_seq" CASCADE'))
                continue
            if dialect == "sqlite":
                connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
                continue

            metadata = MetaData()
            inspector = inspect(engine)
            if not inspector.has_table(table_name):
                continue
            table = Table(table_name, metadata, autoload_with=engine)
            table.drop(connection, checkfirst=True)


def _find_missing_columns(engine: Engine, table_name: str, expected: set[str]) -> list[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return []
    actual = {column["name"] for column in inspector.get_columns(table_name)}
    return sorted(expected - actual)


def _validate_expected_schema(engine: Engine) -> None:
    mismatches: list[str] = []
    for table_name, expected in _EXPECTED_COLUMNS.items():
        missing = _find_missing_columns(engine, table_name, expected)
        if missing:
            missing_text = ", ".join(missing)
            mismatches.append(f"{table_name} 缺少字段: {missing_text}")
    if mismatches:
        detail = "；".join(mismatches)
        raise RuntimeError(
            f"检测到旧版 PostgreSQL 表结构：{detail}。"
            "当前版本不保留旧结构兼容，请执行 `autospider db-init --reset` 重建任务相关表。"
        )


def init_db(reset: bool = False) -> None:
    """初始化数据库：创建所有模型对应的表。

    Args:
        reset: 为 True 时会先删除现有任务相关表，再按当前模型重建。
    """
    from .models import Base

    engine = get_engine()
    if reset:
        _drop_known_tables(engine)
    Base.metadata.create_all(engine)
    _validate_expected_schema(engine)
    logger.info("[DB] 数据库表已初始化")


def close_db() -> None:
    """关闭数据库引擎，释放连接池。"""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
        logger.info("[DB] 引擎已关闭")
    _engine = None
    _SessionFactory = None


atexit.register(close_db)
