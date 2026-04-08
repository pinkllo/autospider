from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessageChunk

from autospider.common.llm.task_clarifier import TaskClarifier
from autospider.domain.chat import DialogueMessage


class _FakeLLM:
    def __init__(self, *chunks: AIMessageChunk):
        self.chunks = list(chunks)
        self.messages = []

    async def astream(self, messages):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


def _make_clarifier(*chunks: AIMessageChunk) -> TaskClarifier:
    clarifier = TaskClarifier.__new__(TaskClarifier)
    clarifier.llm = _FakeLLM(*chunks)
    return clarifier


def test_task_clarifier_accepts_output_text_block_payload(monkeypatch):
    payload = {
        "status": "ready",
        "intent": "采集工程建设分类项目名称",
        "confidence": 0.92,
        "task_description": (
            "访问 https://ygp.gdzwfw.gov.cn/#/44/jygg，"
            "在工程建设下按相关分类采集项目名称，并输出所属分类。"
        ),
        "list_url": "https://ygp.gdzwfw.gov.cn/#/44/jygg",
        "fields": [
            {
                "name": "project_name",
                "description": "项目名称",
                "required": True,
                "data_type": "text",
            },
            {
                "name": "category_name",
                "description": "所属分类",
                "required": True,
                "data_type": "text",
            },
        ],
        "target_url_count": 10,
    }
    response = AIMessageChunk(
        content=[
            {
                "type": "output_text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    )
    clarifier = _make_clarifier(response)
    monkeypatch.setattr("autospider.common.llm.task_clarifier.append_llm_trace", lambda **kwargs: None)

    result = asyncio.run(
        clarifier.clarify(
            [
                DialogueMessage(
                    role="user",
                    content=(
                        "采集网站https://ygp.gdzwfw.gov.cn/#/44/jygg中工程建设下各个相关分类的项目名称，"
                        "各个相关分类每类10条招标项目名称。最终结果需要项目名称，所属分类"
                    ),
                )
            ],
            selected_skills_context="以下是已选中的站点 skills。\n- name: ygp.gdzwfw.gov.cn 站点采集",
        )
    )

    assert result.status == "ready"
    assert result.task is not None
    assert result.task.list_url == "https://ygp.gdzwfw.gov.cn/#/44/jygg"
    assert [field.name for field in result.task.fields] == ["project_name", "category_name"]
