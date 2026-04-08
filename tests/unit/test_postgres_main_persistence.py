from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from autospider.common.config import config
from autospider.common.db.engine import close_db, get_engine, init_db, session_scope
from autospider.common.db.models import TaskRecord, TaskRunItem, TaskRunValidationFailure
from autospider.common.db.repositories import TaskRepository, TaskRunPayload
from autospider.common.storage.task_run_query_service import TaskRunQueryService


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def _configure_database(monkeypatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "autospider_test.sqlite3"
    close_db()
    monkeypatch.setattr(config.database, "url", _sqlite_url(db_path), raising=False)
    monkeypatch.setattr(config.redis, "enabled", False, raising=False)
    return db_path


def test_init_db_reset_replaces_legacy_tables(monkeypatch, tmp_path):
    _configure_database(monkeypatch, tmp_path)
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tasks (id INTEGER PRIMARY KEY, registry_id TEXT)")
        conn.exec_driver_sql("CREATE TABLE task_executions (id INTEGER PRIMARY KEY, task_id INTEGER)")

    init_db(reset=True)

    table_names = set(inspect(engine).get_table_names())
    assert "tasks" in table_names
    assert "task_runs" in table_names
    assert "task_run_items" in table_names
    assert "task_run_validation_failures" in table_names
    assert "task_executions" not in table_names
    close_db()


def test_init_db_without_reset_rejects_legacy_schema(monkeypatch, tmp_path):
    _configure_database(monkeypatch, tmp_path)
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE tasks ("
            "id INTEGER PRIMARY KEY, "
            "registry_id TEXT, "
            "normalized_url TEXT, "
            "original_url TEXT, "
            "task_description TEXT, "
            "created_at TEXT, "
            "updated_at TEXT)"
        )

    try:
        with pytest.raises(RuntimeError, match="db-init --reset"):
            init_db(reset=False)
    finally:
        close_db()


def test_repository_persists_run_and_registry_reads_reusable_history(monkeypatch, tmp_path):
    _configure_database(monkeypatch, tmp_path)
    init_db(reset=True)

    reusable_payload = TaskRunPayload(
        normalized_url="example.com/list",
        original_url="https://example.com/list?page=1",
        page_state_signature="state_engineering",
        anchor_url="https://example.com/root",
        variant_label="工程建设",
        task_description="采集公告",
        field_names=["title", "date"],
        execution_id="exec_reusable",
        thread_id="thread-1",
        output_dir=str(tmp_path / "output"),
        pipeline_mode="redis",
        execution_state="completed",
        outcome_state="success",
        promotion_state="reusable",
        total_urls=2,
        success_count=2,
        failed_count=0,
        validation_failure_count=1,
        success_rate=1.0,
        summary_json={"execution_id": "exec_reusable", "promotion_state": "reusable"},
        collection_config={"nav_steps": ["click:list"]},
        extraction_config={"fields": [{"name": "title", "xpath": "//h1"}]},
        plan_knowledge="plan knowledge",
        committed_records=[
            {
                "url": "https://example.com/detail/1",
                "success": True,
                "failure_reason": "",
                "item": {"url": "https://example.com/detail/1", "title": "公告1"},
            },
            {
                "url": "https://example.com/detail/2",
                "success": False,
                "failure_reason": "missing_date",
                "item": {"url": "https://example.com/detail/2", "title": "公告2"},
            },
        ],
        validation_failures=[
            {
                "url": "https://example.com/detail/2",
                "fields": [{"field_name": "date", "error": "missing"}],
            }
        ],
    )
    diagnostic_payload = TaskRunPayload(
        normalized_url="example.com/list",
        original_url="https://example.com/list?page=2",
        page_state_signature="state_land",
        anchor_url="https://example.com/root",
        variant_label="土地矿业",
        task_description="采集公告",
        field_names=["title", "date"],
        execution_id="exec_diagnostic",
        output_dir=str(tmp_path / "output"),
        execution_state="completed",
        outcome_state="partial_success",
        promotion_state="diagnostic_only",
        total_urls=1,
        success_count=1,
        failed_count=0,
        success_rate=1.0,
        summary_json={"execution_id": "exec_diagnostic", "promotion_state": "diagnostic_only"},
    )

    with session_scope() as session:
        repo = TaskRepository(session)
        repo.save_run(reusable_payload)
        repo.save_run(diagnostic_payload)

    with session_scope() as session:
        assert session.query(TaskRunItem).count() == 2
        assert session.query(TaskRunValidationFailure).count() == 1

    registry = TaskRunQueryService()
    history = registry.find_by_url("https://example.com/list?page=9")

    assert len(history) == 1
    assert history[0]["execution_id"] == "exec_reusable"
    assert history[0]["fields"] == ["title", "date"]
    assert history[0]["collected_count"] == 2
    assert history[0]["page_state_signature"] == "state_engineering"
    assert history[0]["variant_label"] == "工程建设"
    close_db()


def test_repository_allows_same_url_different_page_states(monkeypatch, tmp_path):
    _configure_database(monkeypatch, tmp_path)
    init_db(reset=True)

    with session_scope() as session:
        repo = TaskRepository(session)
        repo.save_run(
            TaskRunPayload(
                normalized_url="example.com/list",
                original_url="https://example.com/list",
                page_state_signature="state_a",
                anchor_url="https://example.com/root",
                variant_label="工程建设",
                task_description="采集公告",
                execution_id="exec_a",
                promotion_state="reusable",
                execution_state="completed",
                outcome_state="success",
                total_urls=1,
                success_count=1,
                success_rate=1.0,
            )
        )
        repo.save_run(
            TaskRunPayload(
                normalized_url="example.com/list",
                original_url="https://example.com/list",
                page_state_signature="state_b",
                anchor_url="https://example.com/root",
                variant_label="土地矿业",
                task_description="采集公告",
                execution_id="exec_b",
                promotion_state="reusable",
                execution_state="completed",
                outcome_state="success",
                total_urls=1,
                success_count=1,
                success_rate=1.0,
            )
        )

    with session_scope() as session:
        assert session.query(TaskRecord).count() == 2
    close_db()


def test_repository_reads_run_detail(monkeypatch, tmp_path):
    _configure_database(monkeypatch, tmp_path)
    init_db(reset=True)

    with session_scope() as session:
        TaskRepository(session).save_run(
            TaskRunPayload(
                normalized_url="example.com/list",
                original_url="https://example.com/list",
                page_state_signature="state_detail",
                anchor_url="https://example.com/root",
                variant_label="公告",
                task_description="采集公告",
                field_names=["title"],
                execution_id="exec_detail",
                pipeline_mode="redis",
                execution_state="completed",
                outcome_state="success",
                promotion_state="reusable",
                total_urls=1,
                success_count=1,
                failed_count=0,
                success_rate=1.0,
                summary_json={"execution_id": "exec_detail"},
                committed_records=[
                    {
                        "url": "https://example.com/detail/1",
                        "success": True,
                        "failure_reason": "",
                        "item": {"url": "https://example.com/detail/1", "title": "公告1"},
                    }
                ],
                validation_failures=[{"url": "https://example.com/detail/1", "fields": []}],
            )
        )

    with session_scope() as session:
        detail = TaskRepository(session).get_run_detail("exec_detail")

    assert detail is not None
    assert detail["task"]["task_description"] == "采集公告"
    assert detail["task"]["page_state_signature"] == "state_detail"
    assert detail["run"]["execution_id"] == "exec_detail"
    assert len(detail["items"]) == 1
    assert detail["items"][0]["item"]["title"] == "公告1"
    close_db()
