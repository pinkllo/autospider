import asyncio
from types import SimpleNamespace

from autospider.domain.chat import ClarificationResult, ClarifiedTask
from autospider.domain.fields import FieldDefinition
from autospider.graph.main_graph import build_main_graph


class _FakeClarifier:
    def __init__(self):
        self.llm = None

    async def clarify(self, history, **kwargs):
        return ClarificationResult(
            status="ready",
            intent="collect",
            confidence=0.95,
            next_question="",
            reason="",
            task=ClarifiedTask(
                intent="collect",
                list_url="https://example.com/list",
                task_description="采集标题",
                fields=[FieldDefinition(name="title", description="标题")],
            ),
        )


class _FakeRuntime:
    def discover_by_url(self, url):
        return []

    async def get_or_select(self, **kwargs):
        return []

    def load_selected_bodies(self, selected):
        return []

    def format_selected_skills_context(self, loaded):
        return ""


class _FakeRegistry:
    def find_by_url(self, url):
        return []


def _initial_chat_state() -> dict:
    return {
        "entry_mode": "chat_pipeline",
        "thread_id": "thread_test",
        "request_id": "req_test",
        "invoked_at": "2026-04-07T23:36:29",
        "cli_args": {"request": "采集 example 网站标题"},
        "conversation": {
            "status": "",
            "flow_state": "",
            "review_state": "",
            "normalized_params": {},
            "clarified_task": None,
            "chat_history": [],
            "chat_turn_count": 0,
            "chat_max_turns": 0,
            "pending_question": "",
            "matched_skills": [],
            "selected_skills": [],
        },
        "planning": {"status": "", "task_plan": None, "plan_knowledge": "", "summary": {}},
        "dispatch": {"status": "", "task_plan": None, "plan_knowledge": "", "dispatch_result": {}, "summary": {}},
        "result": {"status": "", "summary": {}, "data": {}, "artifacts": []},
        "error": None,
        "normalized_params": {},
        "clarified_task": None,
        "chat_history": [],
        "chat_turn_count": 0,
        "chat_max_turns": 0,
        "chat_pending_question": "",
        "chat_flow_state": "",
        "chat_review_state": "",
        "matched_skills": [],
        "selected_skills": [],
        "history_match_done": False,
        "history_match_signature": "",
        "artifacts": [],
        "summary": {},
        "status": "",
        "error_code": "",
        "error_message": "",
    }


def test_chat_graph_persists_clarified_task_until_review_interrupt(monkeypatch):
    import autospider.graph.nodes.entry_nodes as entry_nodes

    monkeypatch.setattr(entry_nodes, "TaskClarifier", _FakeClarifier)
    monkeypatch.setattr(entry_nodes, "SkillRuntime", _FakeRuntime)
    monkeypatch.setattr(entry_nodes, "TaskRegistry", _FakeRegistry)

    graph = build_main_graph()
    result = asyncio.run(
        graph.ainvoke(
            _initial_chat_state(),
            config={"configurable": {"thread_id": "thread_test"}, "recursion_limit": 25},
        )
    )

    interrupts = list(result.get("__interrupt__") or [])
    assert interrupts, "应在 review 阶段触发 interrupt，而不是提前丢失 clarified_task"
    payload = getattr(interrupts[0], "value", None) or interrupts[0].value
    assert payload["type"] == "chat_review"
    assert payload["clarified_task"]["task_description"] == "采集标题"
    assert payload["clarified_task"]["fields"][0]["name"] == "title"
    assert result.get("error") in (None, {})
