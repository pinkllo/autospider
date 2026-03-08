import asyncio
from types import SimpleNamespace

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


def test_plan_node_falls_back_to_single_subtask(monkeypatch):
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

    assert result["node_status"] == "ok"
    plan = result["task_plan"]
    assert len(plan.subtasks) == 1
    assert plan.total_subtasks == 1
    assert plan.subtasks[0].list_url == "https://example.com/list"
    assert plan.subtasks[0].task_description == "抓取公告详情"
    assert result["summary"]["total_subtasks"] == 1
