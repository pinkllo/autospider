from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData
from autospider.contexts.experience.infrastructure.repositories import (
    SkillIndexRepository,
    SkillQueryService,
    SkillRepository,
)


def test_query_service_and_index_repository_lookup_metadata() -> None:
    workspace = _create_local_test_dir()
    try:
        repository = SkillRepository(skills_dir=workspace)
        repository.save_document("example.com", _build_document(domain="example.com", name="example.com 站点采集"))
        repository.save_document("foo.com", _build_document(domain="foo.com", name="foo.com 站点采集"))

        index_repository = SkillIndexRepository(skills_dir=workspace)
        query_service = SkillQueryService(index_repository)

        by_domain = query_service.list_by_domain("example.com")
        by_url = query_service.list_by_url("https://example.com/list")
        all_items = query_service.list_all_metadata()

        assert len(by_domain) == 1
        assert by_domain[0].name == "example.com 站点采集"
        assert len(by_url) == 1
        assert by_url[0].domain == "example.com"
        assert sorted(item.domain for item in all_items) == ["example.com", "foo.com"]
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _build_document(*, domain: str, name: str) -> SkillDocument:
    return SkillDocument(
        frontmatter={"name": name, "description": "示例技能"},
        title=f"# {domain} 采集指南",
        rules=SkillRuleData(
            domain=domain,
            name=name,
            description="示例技能",
            list_url=f"https://{domain}/list",
            task_description="抓取商品信息",
            status="validated",
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


def _create_local_test_dir() -> Path:
    root = Path.cwd() / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"experience_query_test_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
