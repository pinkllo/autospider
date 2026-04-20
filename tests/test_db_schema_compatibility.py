from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.common.db.engine import _validate_expected_schema
from autospider.legacy.common.db.models import Base


def test_validate_expected_schema_upgrades_old_tasks_table_additively() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registry_id VARCHAR(16) NOT NULL,
                normalized_url TEXT NOT NULL,
                original_url TEXT NOT NULL,
                page_state_signature TEXT NOT NULL DEFAULT '',
                anchor_url TEXT NOT NULL DEFAULT '',
                variant_label TEXT NOT NULL DEFAULT '',
                task_description TEXT NOT NULL,
                field_names JSON,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )

    Base.metadata.create_all(engine)

    _validate_expected_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert "semantic_signature" in columns
    assert "strategy_payload" in columns


def test_validate_expected_schema_migrates_old_tasks_unique_index() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registry_id VARCHAR(16) NOT NULL,
                normalized_url TEXT NOT NULL,
                original_url TEXT NOT NULL,
                page_state_signature TEXT NOT NULL DEFAULT '',
                anchor_url TEXT NOT NULL DEFAULT '',
                variant_label TEXT NOT NULL DEFAULT '',
                task_description TEXT NOT NULL,
                field_names JSON,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE UNIQUE INDEX ix_tasks_norm_state_desc
            ON tasks (normalized_url, page_state_signature, task_description)
            """
        )

    Base.metadata.create_all(engine)

    _validate_expected_schema(engine)

    indexes = {item["name"]: item for item in inspect(engine).get_indexes("tasks")}
    assert "ix_tasks_norm_state_desc" not in indexes
    assert "ix_tasks_norm_state_semantic" in indexes
    assert bool(indexes["ix_tasks_norm_state_semantic"]["unique"]) is True

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO tasks (
                registry_id, normalized_url, original_url, page_state_signature,
                anchor_url, variant_label, task_description, semantic_signature,
                strategy_payload, field_names, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                "task0001",
                "example.com/list",
                "https://example.com/list",
                "sig-001",
                "",
                "",
                "采集专业列表",
                "semantic-a",
                "{}",
                "[]",
            ),
        )
        conn.exec_driver_sql(
            """
            INSERT INTO tasks (
                registry_id, normalized_url, original_url, page_state_signature,
                anchor_url, variant_label, task_description, semantic_signature,
                strategy_payload, field_names, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                "task0002",
                "example.com/list",
                "https://example.com/list",
                "sig-001",
                "",
                "",
                "采集专业列表",
                "semantic-b",
                "{}",
                "[]",
            ),
        )
