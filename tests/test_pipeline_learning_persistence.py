from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.platform.persistence.sql.orm.models import Base, TaskRun
from autospider.platform.persistence.sql.orm.repositories import (
    TaskRunPayload,
    TaskRunReadRepository,
    TaskRunWriteRepository,
)


def _make_session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_task_run_payload_exposes_learning_snapshot_fields() -> None:
    payload = TaskRunPayload(
        normalized_url="https://example.com/list",
        original_url="https://example.com/list",
        world_snapshot={"site_profile": {"host": "example.com"}},
        site_profile_snapshot={"host": "example.com"},
        failure_patterns=[{"pattern_id": "loop-detected", "trigger": "ABAB loop"}],
    )

    assert payload.world_snapshot["site_profile"]["host"] == "example.com"
    assert payload.site_profile_snapshot["host"] == "example.com"
    assert payload.failure_patterns[0]["pattern_id"] == "loop-detected"


def test_task_repository_persists_learning_snapshots() -> None:
    session_factory = _make_session_factory()
    payload = TaskRunPayload(
        normalized_url="https://example.com/list",
        original_url="https://example.com/list",
        task_description="collect products",
        semantic_signature="semantic::learning::products",
        execution_id="exec_learning_001",
        world_snapshot={
            "site_profile": {"host": "example.com", "supports_pagination": True},
            "page_models": {"entry": {"page_type": "list_page"}},
        },
        site_profile_snapshot={"host": "example.com", "supports_pagination": True},
        failure_patterns=[{"pattern_id": "loop-detected", "trigger": "ABAB loop"}],
    )

    with session_factory() as session:
        repo = TaskRunWriteRepository(session)
        run = repo.save_run(payload)
        session.commit()
        session.refresh(run)
        assert run.world_snapshot["site_profile"]["host"] == "example.com"
        assert run.site_profile_snapshot["supports_pagination"] is True
        assert run.failure_patterns[0]["pattern_id"] == "loop-detected"

    with session_factory() as session:
        run = session.query(TaskRun).filter(TaskRun.execution_id == "exec_learning_001").one()
        repo = TaskRunReadRepository(session)
        detail = repo.get_run_detail("exec_learning_001")

    assert run.world_snapshot["page_models"]["entry"]["page_type"] == "list_page"
    assert detail is not None
    assert detail["run"]["world_snapshot"]["site_profile"]["host"] == "example.com"
    assert detail["run"]["site_profile_snapshot"]["supports_pagination"] is True
    assert detail["run"]["failure_patterns"][0]["trigger"] == "ABAB loop"
