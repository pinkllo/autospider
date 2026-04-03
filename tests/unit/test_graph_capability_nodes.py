import asyncio
from pathlib import Path
from types import SimpleNamespace

from autospider.common.config import config
from autospider.common.types import TaskPlan
from autospider.graph.nodes import capability_nodes


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


def test_plan_node_fails_when_planner_returns_no_subtasks(monkeypatch):
    async def _fake_execute_planning(*, params, thread_id):
        planner = _FakePlannerEmpty(
            page=SimpleNamespace(url="https://example.com/list"),
            site_url=str(params.get("list_url") or ""),
            user_request=str(params.get("task_description") or ""),
            output_dir=str(params.get("output_dir") or "output"),
        )
        return {
            "task_plan": await planner.plan(),
            "selected_skills": [],
            "summary": {"total_subtasks": 0},
        }

    monkeypatch.setattr(capability_nodes, "execute_planning", _fake_execute_planning)

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
    async def _fake_execute_config_generation(*, params, thread_id):
        return {
            "collection_config": {
                "nav_steps": [{"action": "click", "target": "招标公告"}],
                "common_detail_xpath": "//a[@class=\"detail\"]",
                "pagination_xpath": "//a[@class=\"next\"]",
                "jump_widget_xpath": {"input": "//input", "button": "//button"},
                "list_url": params["list_url"],
                "task_description": params["task"],
            },
            "summary": {
                "nav_steps": 1,
                "has_common_detail_xpath": True,
                "has_pagination_xpath": True,
                "has_jump_widget_xpath": True,
            },
        }

    monkeypatch.setattr(capability_nodes, "execute_config_generation", _fake_execute_config_generation)

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
    async def _fake_execute_batch_collection(*, params, thread_id, collection_config):
        assert collection_config["list_url"] == "https://example.com/list"
        return {
            "collection_config": collection_config,
            "collected_urls": ["https://example.com/a", "https://example.com/b"],
            "collection_progress": {"collected_count": 2},
        }

    monkeypatch.setattr(capability_nodes, "execute_batch_collection", _fake_execute_batch_collection)

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

    async def _fake_execute_url_collection(*, params, thread_id):
        captured.update(params)
        return {
            "collected_urls": ["https://example.com/a"],
            "collection_progress": {"collected_count": 1},
        }

    monkeypatch.setattr(capability_nodes, "execute_url_collection", _fake_execute_url_collection)

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

    async def _fake_execute_batch_collection(*, params, thread_id, collection_config):
        captured.update(params)
        return {
            "collection_config": collection_config,
            "collected_urls": ["https://example.com/a"],
            "collection_progress": {"collected_count": 1},
        }

    monkeypatch.setattr(capability_nodes, "execute_batch_collection", _fake_execute_batch_collection)

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
    async def _fake_execute_field_extraction(*, params, thread_id, collected_urls):
        assert collected_urls == ["https://example.com/a", "https://example.com/b"]
        return {
            "fields_config": [{"name": "title", "xpath": "//h1"}],
            "xpath_result": {
                "fields": [{"name": "title", "xpath": "//h1"}],
                "records": [{"url": "https://example.com/a", "success": True}],
                "total_urls": 2,
                "success_count": 2,
            },
            "summary": {"url_count": 2, "field_count": 1},
        }

    monkeypatch.setattr(capability_nodes, "execute_field_extraction", _fake_execute_field_extraction)

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


def test_run_pipeline_node_exposes_unified_status_fields(monkeypatch, tmp_path):
    async def _fake_execute_pipeline(*, params, thread_id):
        return {
            "total_urls": 4,
            "success_count": 3,
            "failed_count": 1,
            "success_rate": 0.75,
            "required_field_success_rate": 0.75,
            "validation_failure_count": 0,
            "execution_state": "completed",
            "outcome_state": "success",
            "promotion_state": "reusable",
            "items_file": str(tmp_path / "pipeline_extracted_items.jsonl"),
            "execution_id": "exec_123",
        }

    monkeypatch.setattr(capability_nodes, "execute_pipeline", _fake_execute_pipeline)

    result = asyncio.run(
        capability_nodes.run_pipeline_node(
            {
                "thread_id": "thread-1",
                "normalized_params": {
                    "list_url": "https://example.com/list",
                    "task_description": "采集公告",
                    "fields": [{"name": "title", "description": "标题"}],
                    "output_dir": str(tmp_path),
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["pipeline_result"]["outcome_state"] == "success"
    assert result["pipeline_result"]["promotion_state"] == "reusable"
    assert result["pipeline_result"]["success_rate"] == 0.75
    assert result["summary"]["failed_count"] == 1
    assert result["summary"]["execution_state"] == "completed"
