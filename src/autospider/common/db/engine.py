"""数据库引擎管理。

负责 SQLAlchemy Engine / Session 的生命周期管理，
支持通过 DATABASE_URL 切换 PostgreSQL / SQLite / MySQL 等后端。
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from autospider.common.config import config
from autospider.common.logger import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """获取或创建全局数据库引擎（单例）。"""
    global _engine
    if _engine is not None:
        return _engine

    db_config = config.database
    url = db_config.url

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


def init_db() -> None:
    """初始化数据库：创建所有模型对应的表（如果不存在）。"""
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
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
