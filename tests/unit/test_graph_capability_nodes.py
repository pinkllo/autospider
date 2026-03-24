import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from autospider.common.config import config
from autospider.common.types import TaskPlan
from autospider.graph.nodes import capability_nodes


class _FakeBrowserSession:
    def __init__(self, headless=False, **kwargs):
        self.headless = headless
        self.kwargs = kwargs
        self.page = SimpleNamespace(url="https://example.com/list")

    async def start(self):
        return None

    async def stop(self):
        return None


class _FakePlannerEmpty:
    def __init__(self, page, site_url, user_request, output_dir):
        self.page = page
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir

    async def plan(self):
        return TaskPlan(
            plan_id="plan_test",
            original_request=self.user_request,
            site_url=self.site_url,
            subtasks=[],
            total_subtasks=0,
            shared_fields=[],
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )


class _FakeContextManager:
    def __init__(self):
        self.page = SimpleNamespace(url="https://example.com/list")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_plan_node_fails_when_planner_returns_no_subtasks(monkeypatch):
    monkeypatch.setattr(capability_nodes, "BrowserSession", _FakeBrowserSession)
    monkeypatch.setattr(capability_nodes, "TaskPlanner", _FakePlannerEmpty)

    result = asyncio.run(
        capability_nodes.plan_node(
            {
                "normalized_params": {
                    "list_url": "https://example.com/list",
                    "task_description": "抓取公告详情",
                    "fields": [{"name": "title", "description": "标题"}],
                    "max_pages": 5,
                    "target_url_count": 10,
                    "output_dir": "output",
                }
            }
        )
    )

    assert result["node_status"] == "fatal"
    assert result["error_code"] == "planner_no_subtasks"
    assert "未生成任何可执行子任务" in result["error_message"]


def test_generate_config_node_persists_collection_config_in_state(monkeypatch, tmp_path):
    async def _fake_generate_collection_config(**kwargs):
        return SimpleNamespace(
            nav_steps=[{"action": "click", "target": "招标公告"}],
            common_detail_xpath="//a[@class=\"detail\"]",
            pagination_xpath="//a[@class=\"next\"]",
            jump_widget_xpath={"input": "//input", "button": "//button"},
            list_url=kwargs["list_url"],
            task_description=kwargs["task_description"],
        )

    monkeypatch.setattr(capability_nodes, "create_browser_session", lambda **kwargs: _FakeContextManager())
    monkeypatch.setattr(capability_nodes, "generate_collection_config", _fake_generate_collection_config)

    result = asyncio.run(
        capability_nodes.generate_config_node(
            {
                "thread_id": "thread-1",
                "normalized_params": {
                    "list_url": "https://example.com/list",
                    "task": "采集公告",
                    "explore_count": 2,
                    "output_dir": str(tmp_path),
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["collection_config"]["list_url"] == "https://example.com/list"
    assert result["collection_config"]["nav_steps"] == [{"action": "click", "target": "招标公告"}]
    assert result["summary"]["has_common_detail_xpath"] is True


def test_batch_collect_node_can_use_collection_config_from_state(monkeypatch, tmp_path):
    async def _fake_batch_collect_urls(**kwargs):
        config_path = Path(kwargs["config_path"])
        assert config_path.exists()
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert payload["list_url"] == "https://example.com/list"
        return SimpleNamespace(collected_urls=["https://example.com/a", "https://example.com/b"])

    monkeypatch.setattr(capability_nodes, "create_browser_session", lambda **kwargs: _FakeContextManager())
    monkeypatch.setattr(capability_nodes, "batch_collect_urls", _fake_batch_collect_urls)

    result = asyncio.run(
        capability_nodes.batch_collect_node(
            {
                "thread_id": "thread-1",
                "collection_config": {
                    "list_url": "https://example.com/list",
                    "task_description": "采集公告",
                    "nav_steps": [{"action": "click", "target": "招标公告"}],
                    "common_detail_xpath": "//a[@class=\"detail\"]",
                    "pagination_xpath": "//a[@class=\"next\"]",
                    "jump_widget_xpath": {"input": "//input", "button": "//button"},
                },
                "normalized_params": {
                    "output_dir": str(tmp_path),
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["collection_config"]["list_url"] == "https://example.com/list"
    assert result["collected_urls"] == ["https://example.com/a", "https://example.com/b"]
    assert result["collection_progress"]["collected_count"] == 2


def test_collect_urls_node_passes_max_pages_without_mutating_global_config(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    original_max_pages = config.url_collector.max_pages

    async def _fake_collect_detail_urls(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(collected_urls=["https://example.com/a"])

    monkeypatch.setattr(capability_nodes, "create_browser_session", lambda **kwargs: _FakeContextManager())
    monkeypatch.setattr(capability_nodes, "collect_detail_urls", _fake_collect_detail_urls)

    result = asyncio.run(
        capability_nodes.collect_urls_node(
            {
                "thread_id": "thread-1",
                "normalized_params": {
                    "list_url": "https://example.com/list",
                    "task": "采集公告",
                    "explore_count": 2,
                    "max_pages": 9,
                    "output_dir": str(tmp_path),
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert captured["max_pages"] == 9
    assert config.url_collector.max_pages == original_max_pages


def test_batch_collect_node_passes_max_pages_without_mutating_global_config(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    original_max_pages = config.url_collector.max_pages

    async def _fake_batch_collect_urls(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(collected_urls=["https://example.com/a"])

    monkeypatch.setattr(capability_nodes, "create_browser_session", lambda **kwargs: _FakeContextManager())
    monkeypatch.setattr(capability_nodes, "batch_collect_urls", _fake_batch_collect_urls)

    result = asyncio.run(
        capability_nodes.batch_collect_node(
            {
                "thread_id": "thread-1",
                "collection_config": {
                    "list_url": "https://example.com/list",
                    "task_description": "采集公告",
                    "nav_steps": [],
                    "common_detail_xpath": "//a[@class=\"detail\"]",
                    "pagination_xpath": "//a[@class=\"next\"]",
                    "jump_widget_xpath": {"input": "//input", "button": "//button"},
                },
                "normalized_params": {
                    "output_dir": str(tmp_path),
                    "max_pages": 7,
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert captured["max_pages"] == 7
    assert config.url_collector.max_pages == original_max_pages


def test_field_extract_node_uses_checkpoint_urls(monkeypatch, tmp_path):
    async def _fake_run_field_pipeline(**kwargs):
        assert kwargs["urls"] == ["https://example.com/a", "https://example.com/b"]
        return {
            "fields_config": [{"name": "title", "xpath": "//h1"}],
            "xpath_result": {
                "fields": [{"name": "title", "xpath": "//h1"}],
                "records": [{"url": "https://example.com/a", "success": True}],
                "total_urls": 2,
                "success_count": 2,
            },
        }

    monkeypatch.setattr(capability_nodes, "create_browser_session", lambda **kwargs: _FakeContextManager())
    monkeypatch.setattr(capability_nodes, "run_field_pipeline", _fake_run_field_pipeline)

    result = asyncio.run(
        capability_nodes.field_extract_node(
            {
                "thread_id": "thread-1",
                "collected_urls": ["https://example.com/a", "https://example.com/b"],
                "normalized_params": {
                    "fields": [{"name": "title", "description": "标题"}],
                    "output_dir": str(tmp_path),
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["fields_config"] == [{"name": "title", "xpath": "//h1"}]
    assert result["xpath_result"]["total_urls"] == 2
    assert result["summary"]["url_count"] == 2
