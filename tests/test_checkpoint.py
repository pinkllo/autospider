"""断点续爬与基础持久化测试。"""

from __future__ import annotations

import pytest

from autospider.common.storage.persistence import CollectionProgress, ProgressPersistence
from autospider.crawler.base.progress_store import ProgressStore
from autospider.crawler.base.url_publish_service import UrlPublishService
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController


class _FileOwningBackend:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def publish(self, url: str) -> None:
        self.urls.append(url)

    async def list_existing_urls(self) -> list[str]:
        return list(self.urls)

    def persists_published_urls(self) -> bool:
        return True


class TestCollectionProgress:
    def test_default_values(self):
        progress = CollectionProgress()
        assert progress.status == "RUNNING"
        assert progress.pause_reason is None
        assert progress.current_page_num == 1
        assert progress.collected_count == 0
        assert progress.backoff_level == 0
        assert progress.consecutive_success_pages == 0

    def test_to_dict(self):
        progress = CollectionProgress(
            status="PAUSED",
            pause_reason="ANTI_BOT",
            current_page_num=50,
            collected_count=1000,
            backoff_level=2,
        )

        data = progress.to_dict()

        assert data["status"] == "PAUSED"
        assert data["pause_reason"] == "ANTI_BOT"
        assert data["current_page_num"] == 50
        assert data["collected_count"] == 1000
        assert data["backoff_level"] == 2

    def test_from_dict(self):
        data = {
            "status": "COMPLETED",
            "current_page_num": 100,
            "collected_count": 5000,
            "backoff_level": 1,
        }

        progress = CollectionProgress.from_dict(data)

        assert progress.status == "COMPLETED"
        assert progress.current_page_num == 100
        assert progress.collected_count == 5000
        assert progress.backoff_level == 1


class TestProgressPersistence:
    def test_save_and_load_progress(self, tmp_path):
        persistence = ProgressPersistence(tmp_path)
        progress = CollectionProgress(
            status="RUNNING",
            current_page_num=25,
            collected_count=500,
        )

        persistence.save_progress(progress)
        loaded = persistence.load_progress()

        assert loaded is not None
        assert loaded.status == "RUNNING"
        assert loaded.current_page_num == 25
        assert loaded.collected_count == 500
        assert loaded.last_updated != ""

    def test_clear_only_removes_progress_file(self, tmp_path):
        persistence = ProgressPersistence(tmp_path)
        persistence.save_progress(CollectionProgress())
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("http://example.com\n", encoding="utf-8")

        persistence.clear()

        assert not persistence.has_checkpoint()
        assert urls_file.exists()


class TestProgressStore:
    def test_is_compatible_uses_list_url_and_task_description(self, tmp_path):
        store = ProgressStore(output_dir=str(tmp_path))
        store.save(
            status="RUNNING",
            pause_reason=None,
            list_url="https://example.com/list",
            task_description="采集列表",
            current_page_num=2,
            collected_count=4,
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


class TestUrlPublishService:
    @pytest.mark.asyncio
    async def test_file_owning_backend_does_not_write_local_urls(self, tmp_path):
        service = UrlPublishService(
            output_dir=str(tmp_path),
            url_channel=_FileOwningBackend(),
        )

        await service.publish("https://example.com/a")
        service.write_snapshot(["https://example.com/a"])

        assert not (tmp_path / "urls.txt").exists()


class TestAdaptiveRateController:
    def test_default_delay(self):
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )

        assert controller.get_delay() == 1.0
        assert controller.current_level == 0

    def test_apply_penalty(self):
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )

        controller.apply_penalty()
        assert controller.current_level == 1
        assert controller.get_delay() == 1.5

        controller.apply_penalty()
        assert controller.current_level == 2
        assert controller.get_delay() == 2.25

    def test_max_penalty_level(self):
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=2.0,
            max_level=2,
            credit_recovery_pages=5,
        )

        controller.apply_penalty()
        controller.apply_penalty()
        controller.apply_penalty()

        assert controller.current_level == 2

    def test_credit_recovery(self):
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=3,
        )

        controller.apply_penalty()
        assert controller.current_level == 1

        controller.record_success()
        controller.record_success()
        controller.record_success()

        assert controller.current_level == 0

    def test_set_level(self):
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )

        controller.set_level(2)

        assert controller.current_level == 2
        assert controller.get_delay() == 2.25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
