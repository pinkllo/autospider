from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from autospider.contexts.planning.domain.model import SubTask
from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
    ArtifactPlanRepository,
)


def test_artifact_store_round_trips_saved_plan() -> None:
    output_dir = Path("artifacts/test_tmp") / f"planning-artifact-{uuid4().hex}"
    repository = ArtifactPlanRepository(
        site_url="https://example.com/notices",
        user_request="抓取公告",
        output_dir=str(output_dir),
    )
    plan = repository.build_plan(
        [
            SubTask(
                id="subtask-1",
                name="公告",
                list_url="https://example.com/notices",
                task_description="抓取公告标题",
            )
        ]
    )

    saved = repository.save_plan(plan)
    restored = repository._load_saved_plan()

    assert saved.plan_id
    assert restored is not None
    assert restored.total_subtasks == 1
    assert restored.subtasks[0].name == "公告"
