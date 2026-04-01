from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from autospider.common.experience import SkillStore


def _skill_content(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n"
    )


def _make_test_dir() -> Path:
    base = Path(".tmp_test_skill_store") / uuid.uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    return base


def test_list_by_url_returns_skill_metadata_for_same_host():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        store.save(
            "ygp.gdzwfw.gov.cn",
            _skill_content("广东采购公告", "广东采购公告采集技能"),
        )
        store.save(
            "ggzy.gdzwfw.gov.cn",
            _skill_content("广东交易公告", "广东交易公告采集技能"),
        )
        store.save(
            "example.com",
            _skill_content("示例站点", "示例站点采集技能"),
        )

        matched = store.list_by_url("https://ygp.gdzwfw.gov.cn/#/44/jygg")

        assert [item.domain for item in matched] == ["ygp.gdzwfw.gov.cn"]
        assert [item.name for item in matched] == ["广东采购公告"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_find_by_url_keeps_exact_host_lookup():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        exact_content = _skill_content("采购公告", "采购公告采集技能")
        other_content = _skill_content("交易公告", "交易公告采集技能")
        store.save("ygp.gdzwfw.gov.cn", exact_content)
        store.save("ggzy.gdzwfw.gov.cn", other_content)

        assert store.find_by_url("https://ygp.gdzwfw.gov.cn/#/44/jygg") == exact_content
        assert store.find_by_url("https://foo.gdzwfw.gov.cn/list") is None
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_under_agents_path_is_llm_eligible_even_if_content_mentions_draft():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base)
        skill_path = store.save(
            "ygp.gdzwfw.gov.cn",
            _skill_content("广东采购公告", "广东采购公告采集技能（草稿）") + "\n- **状态**: 📝 draft\n",
        )

        matched = store.list_by_url("https://ygp.gdzwfw.gov.cn/#/44/jygg")

        assert store.is_llm_eligible_path(skill_path) is True
        assert [item.domain for item in matched] == ["ygp.gdzwfw.gov.cn"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_skill_under_output_draft_skills_path_is_not_llm_eligible():
    base = _make_test_dir()
    try:
        store = SkillStore(skills_dir=base / "output" / "draft_skills")
        skill_path = store.save(
            "ygp.gdzwfw.gov.cn",
            _skill_content("广东采购公告", "广东采购公告采集技能"),
        )

        matched = store.list_by_url("https://ygp.gdzwfw.gov.cn/#/44/jygg")

        assert store.is_llm_eligible_path(skill_path) is False
        assert matched == []
    finally:
        shutil.rmtree(base, ignore_errors=True)
