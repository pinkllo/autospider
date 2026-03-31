from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from autospider.common.experience import SkillRuntime, SkillStore


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0
        self.model = "fake-model"

    async def ainvoke(self, messages):
        self.calls += 1
        return _FakeResponse(json.dumps(self.payload, ensure_ascii=False))


def _skill_content(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n"
        "正文\n"
    )


def _make_test_dir() -> Path:
    base = Path(".tmp_test_skill_runtime") / uuid.uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    return base


def test_skill_runtime_selects_loads_and_caches():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        store.save("www.doubao.com", _skill_content("doubao-chat", "聊天页技能"))
        store.save("api.doubao.com", _skill_content("doubao-api", "API 技能"))

        runtime = SkillRuntime(store=store)
        llm = _FakeLLM({"selected_indexes": [1], "reasoning": "最相关"})

        async def _run():
            selected_once = await runtime.get_or_select(
                phase="clarifier",
                url="https://www.doubao.com/chat/1",
                task_context={"request": "采集聊天页"},
                llm=llm,
            )
            selected_twice = await runtime.get_or_select(
                phase="clarifier",
                url="https://www.doubao.com/chat/1",
                task_context={"request": "采集聊天页"},
                llm=llm,
            )
            loaded = runtime.load_selected_bodies(selected_once)
            context = runtime.format_selected_skills_context(loaded)
            return selected_once, selected_twice, context

        selected_once, selected_twice, context = asyncio.run(_run())

        assert llm.calls == 1
        assert [item.domain for item in selected_once] == ["www.doubao.com"]
        assert [item.domain for item in selected_twice] == ["www.doubao.com"]
        assert "doubao-chat" in context
        assert "先验经验" in context
    finally:
        shutil.rmtree(base, ignore_errors=True)
