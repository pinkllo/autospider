from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.planning.infrastructure.adapters import (
    analysis_support as analysis_support_module,
)
from autospider.contexts.planning.infrastructure.adapters.analysis_support import (
    PlannerSiteAnalyzer,
)


class _FakeIntent:
    def model_dump(self, mode: str = "python") -> dict[str, object]:
        assert mode == "python"
        return {
            "group_by": "category",
            "per_group_target_count": 3,
            "total_target_count": 12,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": ["采购公告"],
        }


class _FakeRuntime:
    def __init__(self) -> None:
        self.page = SimpleNamespace(url="https://example.com/notices")
        self.llm = SimpleNamespace(model_name="planner-test-model")
        self.site_url = "https://example.com"
        self.user_request = "采集公告"
        self.planner_intent = _FakeIntent()
        self.selected_skills_context = ""
        self.selected_skills = [{"name": "notice-skill"}]
        self.prior_failures = [
            {
                "category": "timeout",
                "detail": "page timed out",
                "metadata": {"subtask_id": "sub_001"},
            }
        ]
        self.post_process_calls: list[dict[str, object]] = []

    def _format_context_path(self, context: dict[str, str] | None) -> str:
        assert context == {"category_name": "公告"}
        return "公告"

    def _format_recent_actions(self, nav_steps: list[dict] | None) -> str:
        assert nav_steps == [{"action": "click", "target_text": "公告"}]
        return "- 点击：公告"

    def _build_planner_candidates(self, snapshot: object, max_candidates: int = 30) -> str:
        assert max_candidates == 30
        assert len(getattr(snapshot, "marks", [])) == 2
        return "- [1] 公告"

    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict:
        self.post_process_calls.append(
            {"result": dict(result), "marks": len(getattr(snapshot, "marks", [])), "context": node_context}
        )
        normalized = dict(result)
        normalized["post_processed"] = True
        return normalized


@pytest.mark.asyncio
async def test_site_analyzer_analyze_site_structure_post_processes_and_traces(
    monkeypatch,
) -> None:
    runtime = _FakeRuntime()
    traces: list[tuple[str, dict[str, object]]] = []

    def _fake_render_template(path: str, section: str, variables: dict | None = None) -> str:
        assert path
        if section == "analyze_site_system_prompt":
            return "system-prompt"
        assert variables is not None
        assert variables["current_category_path"] == "公告"
        assert variables["recent_actions"] == "- 点击：公告"
        assert variables["candidate_elements"] == "- [1] 公告"
        assert "subtask=sub_001" in variables["prior_failure_evidence"]
        return "user-message"

    async def _fake_get_accessibility_text(page) -> str:
        assert page is runtime.page
        return "AX tree"

    async def _fake_ainvoke_with_stream(llm, messages):
        assert llm is runtime.llm
        assert len(messages) == 2
        return {"payload": "ok"}

    def _fake_append_llm_trace(*, component: str, payload: dict[str, object]) -> None:
        traces.append((component, payload))

    monkeypatch.setattr(analysis_support_module, "render_template", _fake_render_template)
    monkeypatch.setattr(
        analysis_support_module,
        "get_accessibility_text",
        _fake_get_accessibility_text,
    )
    monkeypatch.setattr(
        analysis_support_module,
        "ainvoke_with_stream",
        _fake_ainvoke_with_stream,
    )
    monkeypatch.setattr(
        analysis_support_module,
        "extract_response_text_from_llm_payload",
        lambda payload: '{"page_type":"list_page","subtasks":[],"observations":"原始观察"}',
    )
    monkeypatch.setattr(
        analysis_support_module,
        "parse_json_dict_from_llm",
        lambda text: {"page_type": "list_page", "subtasks": [], "observations": text},
    )
    monkeypatch.setattr(
        analysis_support_module,
        "summarize_llm_payload",
        lambda payload: {"status": payload["payload"]},
    )
    monkeypatch.setattr(
        analysis_support_module,
        "append_llm_trace",
        _fake_append_llm_trace,
    )

    snapshot = SimpleNamespace(marks=[1, 2])
    result = await PlannerSiteAnalyzer(runtime)._analyze_site_structure(
        "base64-image",
        snapshot,
        node_context={"category_name": "公告"},
        nav_steps=[{"action": "click", "target_text": "公告"}],
    )

    assert result == {
        "page_type": "list_page",
        "subtasks": [],
        "observations": '{"page_type":"list_page","subtasks":[],"observations":"原始观察"}',
        "post_processed": True,
    }
    assert runtime.post_process_calls == [
        {
            "result": {
                "page_type": "list_page",
                "subtasks": [],
                "observations": '{"page_type":"list_page","subtasks":[],"observations":"原始观察"}',
            },
            "marks": 2,
            "context": {"category_name": "公告"},
        }
    ]
    assert traces[0][0] == "planner_site_analysis"
    assert traces[0][1]["model"] == "planner-test-model"
    assert traces[0][1]["input"]["current_url"] == "https://example.com/notices"
    assert traces[0][1]["response_summary"] == {"status": "ok"}
