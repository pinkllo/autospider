from __future__ import annotations

import pytest

from autospider.contexts.experience.infrastructure.repositories.parsing import (
    SkillDocumentParseError,
    parse_skill_document,
)


def test_parse_skill_document_rejects_unclosed_frontmatter() -> None:
    content = "---\nname: example.com 站点采集\n# example.com 采集指南\n"
    with pytest.raises(SkillDocumentParseError, match="frontmatter is not closed"):
        parse_skill_document(content)


def test_parse_skill_document_rejects_invalid_yaml_frontmatter() -> None:
    content = "---\nname: [broken\n---\n# example.com 采集指南\n"
    with pytest.raises(SkillDocumentParseError, match="invalid YAML frontmatter"):
        parse_skill_document(content)


def test_parse_skill_document_rejects_non_mapping_frontmatter() -> None:
    content = "---\n- a\n- b\n---\n# example.com 采集指南\n"
    with pytest.raises(SkillDocumentParseError, match="frontmatter must be a mapping"):
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
- **主 XPath**: `//h1/text()`
- **验证状态**: ✓ 已验证
- **置信度**: not-a-float
"""
    with pytest.raises(SkillDocumentParseError, match="invalid confidence value"):
        parse_skill_document(content)
