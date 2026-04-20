from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from autospider.legacy.common.db.models import Base, TaskRecord, TaskRun
from autospider.legacy.common.db.repositories.task_repo import (
    TaskRepository,
    TaskRunPayload,
    _build_registry_id,
)
from autospider.legacy.common.storage.task_run_query_service import (
    TaskRunQueryService,
    normalize_url,
)
from autospider.legacy.pipeline.helpers import build_semantic_signature


def _make_session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _build_payload(
    *,
    execution_id: str,
    task_description: str,
    semantic_signature: str | None = None,
    strategy_payload: dict[str, object] | None = None,
    field_names: list[str] | None = None,
) -> TaskRunPayload:
    return TaskRunPayload(
        normalized_url="example.com/list",
        original_url="https://example.com/list?page=1",
        page_state_signature="sig-category",
        task_description=task_description,
        semantic_signature=(
            _expected_semantic_signature() if semantic_signature is None else semantic_signature
        ),
        strategy_payload=dict(
            strategy_payload
            or {
                "group_by": "category",
                "per_group_target_count": 3,
                "category_discovery_mode": "manual",
                "requested_categories": ["土木工程", "交通运输工程"],
                "category_examples": ["交通运输工程"],
            }
        ),
        field_names=list(field_names or ["title", "published_at"]),
        execution_id=execution_id,
        execution_state="completed",
        promotion_state="reusable",
    )


def _expected_semantic_signature() -> str:
    return build_semantic_signature(
        {
            "strategy_payload": {
                "group_by": "category",
                "per_group_target_count": 3,
                "category_discovery_mode": "manual",
                "requested_categories": ["土木工程", "交通运输工程"],
                "category_examples": ["交通运输工程"],
            },
            "fields": [{"name": "title"}, {"name": "published_at"}],
        }
    )


def _insert_legacy_reusable_task(session: Session) -> None:
    _insert_legacy_reusable_task_with_semantics(
        session,
        task_description="按学科分类采集专业列表",
        strategy_payload={
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
            "category_examples": ["交通运输工程"],
        },
        field_names=["title", "published_at"],
    )


def _insert_legacy_reusable_task_with_semantics(
    session: Session,
    *,
    task_description: str,
    strategy_payload: dict[str, object],
    field_names: list[str],
) -> None:
    now = datetime.now()
    task = TaskRecord(
        registry_id=_build_registry_id(
            "example.com/list",
            task_description,
            "sig-category",
        ),
        normalized_url="example.com/list",
        original_url="https://example.com/list?page=1",
        page_state_signature="sig-category",
        task_description=task_description,
        semantic_signature=None,
        strategy_payload=dict(strategy_payload),
        field_names=list(field_names),
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.flush()
    session.add(
        TaskRun(
            task_id=task.id,
            execution_id="exec-legacy-001",
            execution_state="completed",
            promotion_state="reusable",
            started_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()


def test_task_repository_reuses_registry_identity_by_semantic_signature() -> None:
    session_factory = _make_session_factory()
    expected_signature = _expected_semantic_signature()

    with session_factory() as session:
        repo = TaskRepository(session)
        first_run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-001",
                task_description="按学科分类采集专业列表",
            )
        )
        second_run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-002",
                task_description="把专业按分类各抓 3 条",
            )
        )
        first_task_id = first_run.task_id
        second_task_id = second_run.task_id
        session.commit()

        tasks = session.query(TaskRecord).all()

    assert len(tasks) == 1
    assert first_task_id == second_task_id
    assert tasks[0].semantic_signature == expected_signature
    assert tasks[0].registry_id == _build_registry_id(
        "example.com/list",
        expected_signature,
        "sig-category",
    )


def test_task_repository_does_not_merge_legacy_empty_signature_row_by_description_when_semantics_differ() -> (
    None
):
    session_factory = _make_session_factory()
    mismatched_signature = build_semantic_signature(
        {
            "strategy_payload": {
                "group_by": "category",
                "per_group_target_count": 5,
                "category_discovery_mode": "manual",
                "requested_categories": ["交通运输工程"],
                "category_examples": ["交通运输工程"],
            },
            "fields": [{"name": "title"}, {"name": "published_at"}],
        }
    )

    with session_factory() as session:
        _insert_legacy_reusable_task_with_semantics(
            session,
            task_description="按学科分类采集专业列表",
            strategy_payload={
                "group_by": "category",
                "per_group_target_count": 3,
                "category_discovery_mode": "manual",
                "requested_categories": ["土木工程"],
                "category_examples": ["土木工程"],
            },
            field_names=["title", "published_at"],
        )
        repo = TaskRepository(session)
        run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-legacy-mismatch",
                task_description="按学科分类采集专业列表",
                semantic_signature=mismatched_signature,
                strategy_payload={
                    "group_by": "category",
                    "per_group_target_count": 5,
                    "category_discovery_mode": "manual",
                    "requested_categories": ["交通运输工程"],
                    "category_examples": ["交通运输工程"],
                },
            )
        )
        created_task_id = run.task_id
        session.commit()
        tasks = session.query(TaskRecord).order_by(TaskRecord.id.asc()).all()

    assert len(tasks) == 2
    assert created_task_id != tasks[0].id
    assert tasks[0].semantic_signature in (None, "")
    assert tasks[1].semantic_signature == mismatched_signature


def test_task_repository_save_run_computes_missing_semantic_signature_for_new_writes() -> None:
    session_factory = _make_session_factory()
    expected_signature = _expected_semantic_signature()

    with session_factory() as session:
        repo = TaskRepository(session)
        run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-005",
                task_description="按学科分类采集专业列表",
                semantic_signature="",
            )
        )
        actual_signature = str(run.task.semantic_signature or "")
        session.commit()
        task = session.query(TaskRecord).one()
        empty_signature_count = (
            session.query(TaskRecord)
            .filter(
                TaskRecord.normalized_url == "example.com/list",
                TaskRecord.page_state_signature == "sig-category",
                (TaskRecord.semantic_signature.is_(None) | (TaskRecord.semantic_signature == "")),
            )
            .count()
        )

    assert actual_signature == expected_signature
    assert task.semantic_signature == expected_signature
    assert empty_signature_count == 0
    assert task.registry_id == _build_registry_id(
        "example.com/list",
        expected_signature,
        "sig-category",
    )


def test_task_repository_save_run_rejects_new_empty_signature_task_record_when_semantics_missing() -> (
    None
):
    session_factory = _make_session_factory()

    with session_factory() as session:
        repo = TaskRepository(session)
        payload = TaskRunPayload(
            normalized_url="example.com/list",
            original_url="https://example.com/list?page=1",
            page_state_signature="sig-category",
            task_description="按学科分类采集专业列表",
            semantic_signature="",
            strategy_payload={},
            field_names=[],
            execution_id="exec-semantic-007",
            execution_state="completed",
            promotion_state="reusable",
        )

        try:
            repo.save_run(payload)
        except RuntimeError as exc:
            error_message = str(exc)
        else:
            error_message = ""
        task_count = session.query(TaskRecord).count()

    assert error_message == "missing_semantic_signature"
    assert task_count == 0


def test_task_repository_save_run_reconciles_stale_explicit_semantic_signature_to_canonical_identity() -> (
    None
):
    session_factory = _make_session_factory()
    expected_signature = _expected_semantic_signature()

    with session_factory() as session:
        repo = TaskRepository(session)
        first_run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-008",
                task_description="按学科分类采集专业列表",
                semantic_signature=expected_signature,
            )
        )
        second_run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-009",
                task_description="把专业按分类各抓 3 条",
                semantic_signature="stale-semantic-signature",
            )
        )
        first_task_id = first_run.task_id
        second_task_id = second_run.task_id
        session.commit()
        tasks = session.query(TaskRecord).order_by(TaskRecord.id.asc()).all()

    assert len(tasks) == 1
    assert first_task_id == second_task_id
    assert tasks[0].semantic_signature == expected_signature


def test_save_run_with_missing_semantic_signature_upgrades_legacy_history_semantic_first(
    monkeypatch,
) -> None:
    session_factory = _make_session_factory()
    expected_signature = _expected_semantic_signature()

    with session_factory() as session:
        _insert_legacy_reusable_task(session)
        repo = TaskRepository(session)
        run = repo.save_run(
            _build_payload(
                execution_id="exec-semantic-006",
                task_description="把专业按分类各抓 3 条",
                semantic_signature="",
            )
        )
        actual_signature = str(run.task.semantic_signature or "")
        session.commit()
        tasks = session.query(TaskRecord).order_by(TaskRecord.id.asc()).all()

    assert len(tasks) == 1
    assert actual_signature == expected_signature
    assert tasks[0].semantic_signature == expected_signature
    assert tasks[0].registry_id == _build_registry_id(
        "example.com/list",
        expected_signature,
        "sig-category",
    )

    service = TaskRunQueryService()
    monkeypatch.setattr(
        "autospider.legacy.common.storage.task_run_query_service._cache",
        type(
            "_NoopCache",
            (),
            {
                "get": staticmethod(lambda _normalized_url: None),
                "set": staticmethod(lambda _normalized_url, _data, ttl=None: None),
            },
        )(),
    )

    def _db_find_by_url(normalized_url: str) -> list[dict[str, object]]:
        with session_factory() as session:
            return TaskRepository(session).find_by_url(normalized_url)

    monkeypatch.setattr(service, "_db_find_by_url", _db_find_by_url)

    results = service.find_by_url("https://example.com/list?page=9")

    assert len(results) == 1
    assert results[0]["semantic_signature"] == expected_signature
    assert results[0]["registry_id"] == _build_registry_id(
        "example.com/list",
        expected_signature,
        "sig-category",
    )


def test_task_run_query_service_keeps_url_lookup_stable_with_semantic_identity(
    monkeypatch,
) -> None:
    session_factory = _make_session_factory()
    expected_signature = _expected_semantic_signature()

    with session_factory() as session:
        repo = TaskRepository(session)
        repo.save_run(
            _build_payload(
                execution_id="exec-semantic-003",
                task_description="按学科分类采集专业列表",
            )
        )
        repo.save_run(
            _build_payload(
                execution_id="exec-semantic-004",
                task_description="把专业按分类各抓 3 条",
            )
        )
        session.commit()

    service = TaskRunQueryService()
    monkeypatch.setattr(
        "autospider.legacy.common.storage.task_run_query_service._cache",
        type(
            "_NoopCache",
            (),
            {
                "get": staticmethod(lambda _normalized_url: None),
                "set": staticmethod(lambda _normalized_url, _data, ttl=None: None),
            },
        )(),
    )

    def _db_find_by_url(normalized_url: str) -> list[dict[str, object]]:
        with session_factory() as session:
            return TaskRepository(session).find_by_url(normalized_url)

    monkeypatch.setattr(service, "_db_find_by_url", _db_find_by_url)

    results = service.find_by_url("https://example.com/list?page=9")

    assert normalize_url("https://example.com/list?page=9") == "example.com/list"
    assert len(results) == 1
    assert results[0]["semantic_signature"] == expected_signature
    assert results[0]["registry_id"] == _build_registry_id(
        "example.com/list",
        expected_signature,
        "sig-category",
    )
