from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from autospider.composition.container import CompositionContainer
from autospider.contexts.chat.infrastructure.publishers import ChatEventPublisher
from autospider.contexts.planning.infrastructure.publishers import PlanningEventPublisher
from autospider.platform.messaging.in_memory import InMemoryMessaging


def _plan_repository_factory(output_root: Path):
    def _factory(*, site_url: str, user_request: str, output_dir: str):
        from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
            ArtifactPlanRepository,
        )

        del output_dir
        return ArtifactPlanRepository(
            site_url=site_url,
            user_request=user_request,
            output_dir=str(output_root),
        )

    return _factory


@pytest.fixture()
def repo_tmp_dir() -> Path:
    base_dir = Path(".tmp") / "composition-tests"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="composition-container-", dir=base_dir))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.mark.asyncio
async def test_container_builds_in_memory_wiring(repo_tmp_dir: Path) -> None:
    container = CompositionContainer(
        messaging=InMemoryMessaging(),
        plan_repository_factory=_plan_repository_factory(repo_tmp_dir),
    )

    assert isinstance(container.messaging, InMemoryMessaging)
    assert isinstance(container.chat_publisher, ChatEventPublisher)
    assert isinstance(container.planning_publisher, PlanningEventPublisher)
    assert {spec.name for spec in container.subscriptions} == {
        "planning.task_clarified",
        "experience.collection_finalized",
    }

    await container.close()
