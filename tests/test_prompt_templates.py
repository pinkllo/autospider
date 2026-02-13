from __future__ import annotations

import sys
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from common.utils.prompt_template import get_template_sections, render_template


PROMPTS_DIR = project_root / "src" / "autospider" / "prompts"
TEMPLATE_NAMES = ["planner", "decider", "url_collector", "script_generator"]


def _get_test_variables(template_name: str) -> dict:
    if template_name == "planner":
        return {
            "start_url": "https://example.com",
            "task": "收集详情页 URL",
            "target_text": "已中标",
        }
    if template_name == "url_collector":
        return {
            "task_description": "收集政府采购详情页",
            "current_url": "https://example.com/list",
            "visited_count": 5,
            "collected_urls_str": "- https://example.com/detail/1\n- https://example.com/detail/2",
        }
    if template_name == "script_generator":
        return {
            "task_description": "爬取政府采购数据",
            "list_url": "https://example.com/list",
            "nav_summary": '[{"step": 1, "action": "click"}]',
            "visits_count": 3,
            "visits_summary": '[{"url": "https://example.com/detail/1"}]',
            "urls_count": 10,
            "url_samples": '["https://example.com/detail/1"]',
            "url_pattern_analysis": '{"base_url": "https://example.com"}',
        }
    return {}


def test_prompt_templates_have_sections():
    for template_name in TEMPLATE_NAMES:
        template_path = PROMPTS_DIR / f"{template_name}.yaml"
        assert template_path.exists(), f"模板文件不存在: {template_path}"
        sections = get_template_sections(str(template_path))
        assert sections, f"模板无可用 sections: {template_path}"


def test_prompt_template_sections_can_render():
    for template_name in TEMPLATE_NAMES:
        template_path = PROMPTS_DIR / f"{template_name}.yaml"
        sections = get_template_sections(str(template_path))
        variables = _get_test_variables(template_name)
        for section in sections:
            rendered = render_template(str(template_path), section=section, variables=variables)
            assert isinstance(rendered, str)
            assert rendered.strip() != ""
