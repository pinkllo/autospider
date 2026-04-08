from __future__ import annotations

import json

import pytest

from autospider.common.storage.persistence import (
    CollectionConfig,
    CollectionProgress,
    ConfigPersistence,
    ProgressPersistence,
)
from autospider.crawler.base.progress_store import ProgressStore
from autospider.crawler.base.url_publish_service import UrlPublishService
from autospider.domain.planning import SubTask, SubTaskStatus, TaskPlan
from autospider.graph.subgraphs.multi_dispatch import _build_dispatch_summary


class _PersistingBackend:
    def __init__(self, urls: list[str] | None = None) -> None:
        self.urls = list(urls or [])

    async def publish(self, url: str) -> None:
        self.urls.append(url)

    async def list_existing_urls(self) -> list[str]:
        return list(self.urls)

    def persists_published_urls(self) -> bool:
        return True


class _ExplodingBackend:
    async def publish(self, url: str) -> None:
        raise RuntimeError(f"publish_failed:{url}")

    async def list_existing_urls(self) -> list[str]:
        return []

    def persists_published_urls(self) -> bool:
        return False


def test_url_publish_service_append_local_urls_is_idempotent(tmp_path):
    service = UrlPublishService(output_dir=str(tmp_path))

    service.append_local_urls(["https://example.com/b", "https://example.com/a", "https://example.com/b"])
    service.append_local_urls(["https://example.com/c", "https://example.com/a"])

    content = (tmp_path / "urls.txt").read_text(encoding="utf-8")
    assert content == "https://example.com/b\nhttps://example.com/a\nhttps://example.com/c\n"

    service.append_local_urls(["https://example.com/c"])
    assert (tmp_path / "urls.txt").read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_url_publish_service_load_existing_urls_merges_backend_and_local(tmp_path):
    (tmp_path / "urls.txt").write_text(
        "https://example.com/b\nhttps://example.com/c\n",
        encoding="utf-8",
    )
    service = UrlPublishService(
        output_dir=str(tmp_path),
        url_channel=_PersistingBackend(["https://example.com/a", "https://example.com/b"]),
    )

    assert await service.load_existing_urls() == [
        "https://example.com/a",
        "https://example.com/b",
    ]

    service = UrlPublishService(output_dir=str(tmp_path))
    assert await service.load_existing_urls() == [
        "https://example.com/b",
        "https://example.com/c",
    ]


@pytest.mark.asyncio
async def test_url_publish_service_publish_raises_backend_errors(tmp_path):
    service = UrlPublishService(
        output_dir=str(tmp_path),
        url_channel=_ExplodingBackend(),
    )

    with pytest.raises(RuntimeError, match="publish_failed:https://example.com/a"):
        await service.publish("https://example.com/a")


def test_progress_store_load_raises_for_corrupt_file(tmp_path):
    store = ProgressStore(output_dir=str(tmp_path))
    (tmp_path / "progress.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(RuntimeError, match="failed_to_load_collection_progress"):
        store.load()


def test_progress_store_compatibility_only_uses_task_identity(tmp_path):
    store = ProgressStore(output_dir=str(tmp_path))
    store.save(
        status="completed",
        pause_reason=None,
        list_url="https://example.com/list",
        task_description="采集列表",
        current_page_num=3,
        collected_count=5,
        backoff_level=1,
        consecutive_success_pages=2,
    )

    progress = store.load()
    assert progress is not None
    assert store.is_compatible(
        progress,
        list_url="https://example.com/list",
        task_description="采集列表",
    )
    assert not store.is_compatible(
        progress,
        list_url="https://example.com/other",
        task_description="采集列表",
    )


def test_progress_persistence_clear_only_removes_progress_file(tmp_path):
    persistence = ProgressPersistence(output_dir=tmp_path)
    persistence.save_progress(CollectionProgress(status="RUNNING", current_page_num=2))
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com/a\n", encoding="utf-8")

    persistence.clear()

    assert not (tmp_path / "progress.json").exists()
    assert urls_file.exists()
    assert urls_file.read_text(encoding="utf-8") == "https://example.com/a\n"


def test_config_persistence_save_does_not_inject_timestamps(tmp_path):
    persistence = ConfigPersistence(config_dir=tmp_path)
    config = CollectionConfig(
        list_url="https://example.com/list",
        task_description="采集列表",
        nav_steps=[{"action": "click", "target": "招标公告"}],
    )

    persistence.save(config)
    first = json.loads((tmp_path / "collection_config.json").read_text(encoding="utf-8"))
    persistence.save(config)
    second = json.loads((tmp_path / "collection_config.json").read_text(encoding="utf-8"))

    assert first == second
    assert first["created_at"] == ""
    assert first["updated_at"] == ""


def test_config_persistence_load_raises_for_corrupt_file(tmp_path):
    persistence = ConfigPersistence(config_dir=tmp_path)
    (tmp_path / "collection_config.json").write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="failed_to_load_collection_config"):
        persistence.load()


def test_build_dispatch_summary_keeps_plan_timestamp_stable():
    plan = TaskPlan(
        plan_id="plan_01",
        original_request="采集项目",
        site_url="https://example.com",
        created_at="fixed-ts",
        updated_at="fixed-ts",
        subtasks=[
            SubTask(
                id="sub_01",
                name="子任务",
                list_url="https://example.com/list",
                task_description="采集子任务",
                status=SubTaskStatus.PENDING,
            )
        ],
        total_subtasks=1,
    )
    result_item = {
        "id": "sub_01",
        "status": SubTaskStatus.COMPLETED.value,
        "error": "",
        "result_file": "output/pipeline_extracted_items.jsonl",
        "collected_count": 3,
    }

    first = _build_dispatch_summary(plan, [result_item])
    second = _build_dispatch_summary(plan, [result_item])

    assert first == second
    assert plan.updated_at == "fixed-ts"
