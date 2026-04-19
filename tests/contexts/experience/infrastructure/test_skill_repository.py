from __future__ import annotations

import pytest
import shutil
from pathlib import Path
from uuid import uuid4

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData
from autospider.contexts.experience.infrastructure.repositories import (
    SkillRepository,
    parse_skill_document,
)


def test_skill_repository_round_trips_skill_document() -> None:
    workspace = _create_local_test_dir()
    try:
        repository = SkillRepository(skills_dir=workspace)
        document = SkillDocument(
            frontmatter={"name": "example.com 站点采集", "description": "示例技能"},
            title="# example.com 采集指南",
            rules=SkillRuleData(
                domain="example.com",
                name="example.com 站点采集",
                description="示例技能",
                list_url="https://example.com/list",
                task_description="抓取商品信息",
                status="validated",
                detail_xpath="//a[@class='detail']",
                fields={
                    "title": SkillFieldRule(
                        name="title",
                        description="标题",
                        primary_xpath="//h1/text()",
                        validated=True,
                        confidence=0.9,
                    )
                },
            ),
        )

        path = repository.save_document("example.com", document)
        content = repository.load_by_path(path)
        parsed = parse_skill_document(content)

        assert repository.list_by_url("https://example.com/list")[0].name == "example.com 站点采集"
        assert repository.list_by_domain("example.com")[0].domain == "example.com"
        assert len(repository.list_all_metadata()) == 1
        assert parsed.rules.detail_xpath == "//a[@class='detail']"
        assert parsed.rules.fields["title"].primary_xpath == "//h1/text()"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_parse_skill_document_rejects_unclosed_frontmatter() -> None:
    content = "---\nname: example.com 站点采集\ndescription: 示例技能\n# example.com 采集指南\n"

    with pytest.raises(ValueError, match="frontmatter"):
        parse_skill_document(content)


def test_parse_skill_document_rejects_invalid_confidence() -> None:
    content = """---
name: example.com 站点采集
description: 示例技能
---
# example.com 采集指南

## 基本信息
- **列表页 URL**: `https://example.com/list`
- **任务描述**: 抓取商品信息
- **状态**: validated

## 字段提取规则
### title（标题）
- **数据类型**: text
- **提取方式**: xpath
- **主 XPath**: `//h1/text()`
- **置信度**: not-a-number
"""

    with pytest.raises(ValueError, match="invalid confidence"):
        parse_skill_document(content)


def _create_local_test_dir() -> Path:
    root = Path.cwd() / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"experience_repo_test_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
