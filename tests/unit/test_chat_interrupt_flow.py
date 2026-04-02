import asyncio

from autospider.common.experience import SkillMetadata
from autospider.graph.nodes import entry_nodes


class _NeedClarificationResult:
    status = "need_clarification"
    task = None
    reason = ""
    next_question = "请补充列表页 URL"


class _FakeClarifierNeedQuestion:
    def __init__(self):
        self.llm = object()

    async def clarify(
        self,
        history,
        *,
        available_skills=None,
        selected_skills=None,
        selected_skills_context=None,
    ):
        assert history[0].content == "帮我抓取公告"
        return _NeedClarificationResult()


class _ReadyResult:
    status = "ready"
    reason = ""
    next_question = ""

    def __init__(self, task):
        self.task = task


class _FakeClarifierReady:
    def __init__(self):
        self.llm = object()

    async def clarify(
        self,
        history,
        *,
        available_skills=None,
        selected_skills=None,
        selected_skills_context=None,
    ):
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


def test_chat_review_task_approve_keeps_chat_on_planning_dispatch_path(monkeypatch):
    monkeypatch.setattr(entry_nodes, "interrupt", lambda payload: {"action": "approve"})

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
    assert result["chat_review_state"] == "approved"


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


class _FakeClarifierWithSkills:
    def __init__(self):
        self.llm = object()

    async def clarify(
        self,
        history,
        *,
        available_skills=None,
        selected_skills=None,
        selected_skills_context=None,
    ):
        assert history[0].content == "帮我抓取 https://www.doubao.com/chat/38419498708783618 的内容"
        assert available_skills == [
            {
                "name": "doubao-chat",
                "description": "抖包聊天页采集技能",
                "path": "d:/autospider/.agents/skills/www.doubao.com/SKILL.md",
                "domain": "www.doubao.com",
            }
        ]
        assert selected_skills == available_skills
        assert "抖包聊天页采集技能" in (selected_skills_context or "")
        return _NeedClarificationResult()


class _FakeSkillRuntime:
    def discover_by_url(self, url):
        assert url == "https://www.doubao.com/chat/38419498708783618"
        return [
            SkillMetadata(
                name="doubao-chat",
                description="抖包聊天页采集技能",
                path="d:/autospider/.agents/skills/www.doubao.com/SKILL.md",
                domain="www.doubao.com",
            )
        ]

    async def get_or_select(self, **kwargs):
        return self.discover_by_url(kwargs["url"])

    def load_selected_bodies(self, selected_skills):
        return [
            type(
                "LoadedSkill",
                (),
                {
                    "name": selected_skills[0].name,
                    "description": selected_skills[0].description,
                    "path": selected_skills[0].path,
                    "domain": selected_skills[0].domain,
                    "content": "# doubao-chat\n正文",
                },
            )()
        ]

    def format_selected_skills_context(self, loaded_skills):
        skill = loaded_skills[0]
        return (
            "以下是已选中的站点 skills。\n"
            f"- name: {skill.name}\n"
            f"- description: {skill.description}\n"
            f"{skill.content}"
        )


def test_chat_clarify_discovers_same_host_skills(monkeypatch):
    monkeypatch.setattr(entry_nodes, "TaskClarifier", _FakeClarifierWithSkills)
    monkeypatch.setattr(entry_nodes, "SkillRuntime", _FakeSkillRuntime)

    result = asyncio.run(
        entry_nodes.chat_clarify(
            {
                "cli_args": {
                    "request": "帮我抓取 https://www.doubao.com/chat/38419498708783618 的内容",
                    "max_turns": 3,
                },
                "chat_history": [],
                "chat_turn_count": 0,
            }
        )
    )

    assert result["node_status"] == "ok"
    assert result["matched_skills"] == [
        {
            "name": "doubao-chat",
            "description": "抖包聊天页采集技能",
            "path": "d:/autospider/.agents/skills/www.doubao.com/SKILL.md",
            "domain": "www.doubao.com",
        }
    ]
    assert result["selected_skills"] == result["matched_skills"]
