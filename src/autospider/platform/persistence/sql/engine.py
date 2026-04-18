from __future__ import annotations

from os import getenv

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite+pysqlite:///:memory:"


def resolve_database_url(override: str | None = None) -> str:
    return str(override or getenv("AUTOSPIDER_DB_URL") or DEFAULT_DB_URL).strip()


def build_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    return create_engine(resolve_database_url(database_url), echo=echo, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
