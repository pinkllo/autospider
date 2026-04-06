from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from autospider.common.experience import SkillRuntime, SkillSedimenter, SkillStore
from autospider.common.experience.skill_store import parse_skill_document


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0
        self.model = "fake-model"
        self.messages = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages.append(messages)
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


def test_skill_runtime_reuses_preselected_skills_without_reselection():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        store.save("www.doubao.com", _skill_content("doubao-chat", "聊天页技能"))

        runtime = SkillRuntime(store=store)
        llm = _FakeLLM({"selected_indexes": [1], "reasoning": "最相关"})
        seeded = runtime.discover_by_url("https://www.doubao.com/chat/1")

        async def _run():
            return await runtime.get_or_select(
                phase="planner",
                url="https://www.doubao.com/chat/1",
                task_context={"request": "采集聊天页", "fields": [{"name": "title"}]},
                llm=llm,
                preselected_skills=seeded,
            )

        selected = asyncio.run(_run())

        assert llm.calls == 0
        assert [item.domain for item in selected] == ["www.doubao.com"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_runtime_formats_available_skills_as_structured_json():
    runtime = SkillRuntime()
    rendered = runtime._format_available_skills(
        [
            type("Meta", (), {
                "name": "站点 A",
                "description": "说明 A",
                "domain": "a.example.com",
            })(),
            type("Meta", (), {
                "name": "站点 B",
                "description": "说明 B",
                "domain": "b.example.com",
            })(),
        ]
    )

    payload = json.loads(rendered)
    assert payload == [
        {"index": 1, "name": "站点 A", "description": "说明 A", "domain": "a.example.com"},
        {"index": 2, "name": "站点 B", "description": "说明 B", "domain": "b.example.com"},
    ]


def test_skill_runtime_autocorrects_zero_based_index_from_model():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        store.save("www.doubao.com", _skill_content("doubao-chat", "聊天页技能"))

        runtime = SkillRuntime(store=store)
        llm = _FakeLLM({"selected_indexes": [0], "reasoning": "第一个 skill 最相关"})

        async def _run():
            return await runtime.get_or_select(
                phase="url_collector",
                url="https://www.doubao.com/chat/1",
                task_context={"request": "采集聊天页"},
                llm=llm,
            )

        selected = asyncio.run(_run())

        assert [item.domain for item in selected] == ["www.doubao.com"]
        assert llm.calls == 1
        prompt_text = llm.messages[0][1].content
        assert '"index": 1' in prompt_text
        assert '不能返回 0' in prompt_text
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_store_keeps_validated_skill_on_lower_quality_update():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        validated = (
            "---\n"
            "name: example.com 站点采集\n"
            "description: example.com 数据采集技能。状态: 已验证。\n"
            "---\n\n"
            "# example.com 采集指南\n\n"
            "## 基本信息\n\n"
            "- **列表页 URL**: `https://example.com/list`\n"
            "- **任务描述**: 采集标题\n"
            "- **状态**: ✅ validated\n"
            "- **成功率**: 100% (10/10)\n\n"
            "## 字段提取规则\n\n"
            "### 标题\n\n"
            "- **数据类型**: text\n"
            "- **主 XPath**: `//h1`\n"
            "- **验证状态**: ✓ 已验证\n"
            "- **置信度**: 0.9\n\n"
            "## 站点特征与经验\n\n"
            "稳定经验\n"
        )
        degraded = validated.replace("100% (10/10)", "50% (5/10)").replace("//h1", "//div/h1").replace("稳定经验", "低质量经验")

        store.save("example.com", validated)
        store.save("example.com", degraded)
        loaded = store.load("example.com") or ""
        parsed = parse_skill_document(loaded)

        assert "100% (10/10)" in loaded
        assert "//h1" in loaded
        assert "//div/h1" not in loaded
        assert parsed.insights_markdown == "低质量经验"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_store_preserves_previous_xpath_as_fallback_on_upgrade():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        old_skill = (
            "---\n"
            "name: example.com 站点采集\n"
            "description: example.com 数据采集技能。状态: 已验证。\n"
            "---\n\n"
            "# example.com 采集指南\n\n"
            "## 基本信息\n\n"
            "- **列表页 URL**: `https://example.com/list`\n"
            "- **任务描述**: 采集标题\n"
            "- **状态**: ✅ validated\n"
            "- **成功率**: 80% (8/10)\n\n"
            "## 字段提取规则\n\n"
            "### 标题\n\n"
            "- **数据类型**: text\n"
            "- **主 XPath**: `//h1`\n"
            "- **验证状态**: ✓ 已验证\n"
            "- **置信度**: 0.8\n\n"
            "## 站点特征与经验\n\n"
            "旧经验\n"
        )
        new_skill = (
            "---\n"
            "name: example.com 站点采集\n"
            "description: example.com 数据采集技能。状态: 已验证。\n"
            "---\n\n"
            "# example.com 采集指南\n\n"
            "## 基本信息\n\n"
            "- **列表页 URL**: `https://example.com/list`\n"
            "- **任务描述**: 采集标题\n"
            "- **状态**: ✅ validated\n"
            "- **成功率**: 90% (9/10)\n\n"
            "## 字段提取规则\n\n"
            "### 标题\n\n"
            "- **数据类型**: text\n"
            "- **主 XPath**: `//main/h1`\n"
            "- **验证状态**: ✓ 已验证\n"
            "- **置信度**: 0.9\n\n"
            "## 站点特征与经验\n\n"
            "新经验\n"
        )

        store.save("example.com", old_skill)
        store.save("example.com", new_skill)
        loaded = store.load("example.com") or ""
        parsed = parse_skill_document(loaded)

        assert "//main/h1" in loaded
        assert "- **备选 XPath**: `//h1`" in loaded
        assert parsed.rules.fields["标题"].primary_xpath == "//main/h1"
        assert parsed.rules.fields["标题"].fallback_xpaths == ["//h1"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_sedimenter_outputs_structured_document_via_store_renderer():
    base = _make_test_dir()
    try:
        sedimenter = SkillSedimenter(skills_dir=base)
        saved = sedimenter.sediment_from_pipeline_result(
            list_url="https://example.com/list",
            task_description="采集标题",
            fields=[{"name": "标题", "description": "文章标题"}],
            collection_config={
                "common_detail_xpath": "//article/a",
                "jump_widget_xpath": {
                    "input": "input.page",
                    "button": "button.jump",
                },
                "nav_steps": [
                    {
                        "action": "click",
                        "target_xpath": "//button[@id='tab-all']",
                        "description": "切换到全部",
                    }
                ],
            },
            extraction_config={
                "fields": [
                    {
                        "name": "标题",
                        "xpath": "//h1",
                        "xpath_fallbacks": ["//main/h1"],
                        "xpath_validated": True,
                        "data_type": "text",
                    }
                ]
            },
            summary={"success_count": 3, "total_urls": 3},
            validation_failures=[],
            subtask_names=["公告", "结果"],
            plan_knowledge="",
            status="validated",
        )

        assert saved is not None
        loaded = (saved or base).read_text(encoding="utf-8")
        parsed = parse_skill_document(loaded)

        assert parsed.rules.name == "example.com 站点采集"
        assert parsed.rules.description == "example.com 数据采集技能。包含列表页导航、分页处理和字段提取的操作指南。状态: 已验证。"
        assert parsed.rules.detail_xpath == "//article/a"
        assert parsed.rules.jump_input_selector == "input.page"
        assert parsed.rules.jump_button_selector == "button.jump"
        assert parsed.rules.subtask_names == ["公告", "结果"]
        assert parsed.rules.fields["标题"].primary_xpath == "//h1"
        assert parsed.rules.fields["标题"].fallback_xpaths == ["//main/h1"]
        assert parsed.rules.fields["标题"].validated is True
        assert parsed.rules.success_rate_text == "100% (3/3)"
        assert "## 子任务" in loaded
        assert "## 站点特征与经验" in loaded
    finally:
        shutil.rmtree(base, ignore_errors=True)
