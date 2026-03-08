import asyncio

from autospider.graph.nodes import entry_nodes


class _NeedClarificationResult:
    status = "need_clarification"
    task = None
    reason = ""
    next_question = "请补充列表页 URL"


class _FakeClarifierNeedQuestion:
    async def clarify(self, history):
        assert history[0].content == "帮我抓取公告"
        return _NeedClarificationResult()


class _ReadyResult:
    status = "ready"
    reason = ""
    next_question = ""

    def __init__(self, task):
        self.task = task


class _FakeClarifierReady:
    async def clarify(self, history):
        return _ReadyResult(
            entry_nodes.ClarifiedTask(
                intent="采集公告",
                list_url="https://example.com/list",
                task_description="采集公告详情",
                fields=[
                    entry_nodes.FieldDefinition(
                        name="title",
                        description="标题",
                        required=True,
                        data_type="text",
                        example=None,
                    )
                ],
            )
        )


def test_chat_clarify_need_input(monkeypatch):
    monkeypatch.setattr(entry_nodes, "TaskClarifier", _FakeClarifierNeedQuestion)

    result = asyncio.run(
        entry_nodes.chat_clarify(
            {
                "cli_args": {"request": "帮我抓取公告", "max_turns": 3},
                "chat_history": [],
                "chat_turn_count": 0,
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["chat_flow_state"] == "needs_input"
    assert result["chat_turn_count"] == 1
    assert result["chat_pending_question"] == "请补充列表页 URL"
    assert result["chat_history"] == [{"role": "user", "content": "帮我抓取公告"}]


def test_chat_collect_user_input_appends_history(monkeypatch):
    monkeypatch.setattr(entry_nodes, "interrupt", lambda payload: {"answer": "列表页是 https://example.com/list"})

    result = asyncio.run(
        entry_nodes.chat_collect_user_input(
            {
                "thread_id": "thread_chat",
                "cli_args": {"request": "帮我抓取公告", "max_turns": 3},
                "chat_history": [{"role": "user", "content": "帮我抓取公告"}],
                "chat_turn_count": 1,
                "chat_max_turns": 3,
                "chat_pending_question": "请补充列表页 URL",
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["chat_pending_question"] == ""
    assert result["chat_flow_state"] == "input_collected"
    assert result["chat_history"][-2:] == [
        {"role": "assistant", "content": "请补充列表页 URL"},
        {"role": "user", "content": "列表页是 https://example.com/list"},
    ]


def test_chat_review_task_supplement_returns_to_clarify(monkeypatch):
    monkeypatch.setattr(
        entry_nodes,
        "interrupt",
        lambda payload: {"action": "supplement", "message": "字段里再加上发布时间"},
    )

    result = asyncio.run(
        entry_nodes.chat_review_task(
            {
                "thread_id": "thread_chat",
                "cli_args": {"request": "帮我抓取公告"},
                "chat_history": [{"role": "user", "content": "帮我抓取公告"}],
                "clarified_task": {
                    "intent": "采集公告",
                    "list_url": "https://example.com/list",
                    "task_description": "采集公告详情",
                    "fields": [
                        {
                            "name": "title",
                            "description": "标题",
                            "required": True,
                            "data_type": "text",
                            "example": None,
                        }
                    ],
                },
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["chat_review_state"] == "reclarify"
    assert result["clarified_task"] is None
    assert result["chat_history"][-1] == {"role": "user", "content": "字段里再加上发布时间"}


def test_chat_clarify_ready_from_override(monkeypatch):
    monkeypatch.setattr(entry_nodes, "TaskClarifier", _FakeClarifierReady)

    result = asyncio.run(
        entry_nodes.chat_clarify(
            {
                "cli_args": {"request": "帮我抓取公告", "max_turns": 3},
                "chat_history": [{"role": "user", "content": "帮我抓取公告"}],
                "chat_turn_count": 1,
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["chat_flow_state"] == "ready"
    assert result["clarified_task"]["list_url"] == "https://example.com/list"
    assert result["clarified_task"]["fields"][0]["name"] == "title"
