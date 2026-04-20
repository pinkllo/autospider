"""Collection adapter for generating follow-up detail crawler scripts."""

from __future__ import annotations

import re
from typing import Any

from autospider.legacy.common.logger import get_logger
from autospider.contexts.collection.infrastructure.adapters._scrapy_script_template import (
    build_detail_crawler_script,
)
from autospider.contexts.collection.infrastructure.repositories.config_repository import (
    ConfigPersistence,
)

logger = get_logger(__name__)


class ScriptGenerator:
    def __init__(self, output_dir: str = "output"):
        self.config_persistence = ConfigPersistence(output_dir)

    async def generate_scrapy_playwright_script(
        self,
        list_url: str,
        task_description: str,
        detail_visits: list[dict[str, Any]],
        nav_steps: list[dict[str, Any]],
        collected_urls: list[str],
        common_detail_xpath: str | None = None,
    ) -> str:
        logger.info("[ScriptGenerator] 开始分析探索记录...")
        nav_steps, common_detail_xpath = self._hydrate_missing_config(
            nav_steps, common_detail_xpath
        )
        if not detail_visits:
            logger.info("[ScriptGenerator] 没有探索记录，无法生成脚本")
            return ""
        nav_xpaths = self._extract_nav_xpaths(nav_steps)
        logger.info("[ScriptGenerator] 提取到 %s 个导航步骤的 xpath", len(nav_xpaths))
        detail_xpath = common_detail_xpath or self._extract_detail_xpath(detail_visits)
        logger.info("[ScriptGenerator] 详情链接 xpath: %s", detail_xpath or "N/A")
        if not nav_xpaths and not detail_xpath:
            logger.info("[ScriptGenerator] 无法生成脚本（缺少 xpath 信息）")
            return ""
        script = build_detail_crawler_script(
            list_url=list_url,
            task_description=task_description,
            nav_xpaths=nav_xpaths,
            detail_xpath=detail_xpath,
        )
        if script:
            logger.info("[ScriptGenerator] 脚本生成完成（%s 字符）", len(script))
            self._validate_script(script)
        return script

    def _hydrate_missing_config(
        self,
        nav_steps: list[dict[str, Any]],
        common_detail_xpath: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if (nav_steps or common_detail_xpath) or not self.config_persistence.exists():
            return nav_steps, common_detail_xpath
        logger.info("[ScriptGenerator] 尝试从配置文件读取缺失的参数...")
        saved_config = self.config_persistence.load()
        if saved_config is None:
            return nav_steps, common_detail_xpath
        resolved_nav_steps = nav_steps or saved_config.nav_steps
        resolved_detail_xpath = common_detail_xpath or saved_config.common_detail_xpath
        if resolved_nav_steps:
            logger.info("[ScriptGenerator] 从配置读取到 %s 个导航步骤", len(resolved_nav_steps))
        if resolved_detail_xpath:
            logger.info("[ScriptGenerator] 从配置读取到公共 xpath: %s", resolved_detail_xpath)
        return resolved_nav_steps, resolved_detail_xpath

    def _extract_nav_xpaths(self, nav_steps: list[dict[str, Any]]) -> list[dict[str, str]]:
        nav_xpaths: list[dict[str, str]] = []
        for step in nav_steps:
            if not step.get("success") or str(step.get("action", "")).lower() != "click":
                continue
            xpath_candidates = list(step.get("clicked_element_xpath_candidates", []) or [])
            if not xpath_candidates:
                continue
            sorted_candidates = sorted(xpath_candidates, key=lambda item: item.get("priority", 99))
            best_xpath = sorted_candidates[0].get("xpath") if sorted_candidates else None
            if not best_xpath:
                continue
            nav_xpaths.append(
                {
                    "xpath": str(best_xpath),
                    "text": str(step.get("clicked_element_text") or step.get("target_text", "")),
                    "action": "click",
                }
            )
        return nav_xpaths

    def _extract_detail_xpath(self, detail_visits: list[dict[str, Any]]) -> str | None:
        if len(detail_visits) < 2:
            return None
        all_xpaths: list[str] = []
        for visit in detail_visits:
            xpath_candidates = list(visit.get("clicked_element_xpath_candidates", []) or [])
            sorted_candidates = sorted(xpath_candidates, key=lambda item: item.get("priority", 99))
            if sorted_candidates:
                all_xpaths.append(str(sorted_candidates[0].get("xpath", "")))
        if not all_xpaths:
            return None
        normalized_xpaths = [re.sub(r"\[\d+\]", "", xpath) for xpath in all_xpaths]
        unique_patterns = set(normalized_xpaths)
        if len(unique_patterns) == 1:
            return list(unique_patterns)[0]
        return None

    def _validate_script(self, script: str) -> None:
        if "async_playwright" in script and "DetailCrawler" in script:
            logger.info("[ScriptGenerator] 详情页 Playwright 脚本结构验证通过")
            return
        logger.info("[ScriptGenerator] 生成结果未命中预期脚本结构")


async def generate_crawler_script(
    list_url: str,
    task_description: str,
    detail_visits: list[dict[str, Any]],
    nav_steps: list[dict[str, Any]],
    collected_urls: list[str],
    common_detail_xpath: str | None = None,
    output_dir: str = "output",
) -> str:
    generator = ScriptGenerator(output_dir)
    return await generator.generate_scrapy_playwright_script(
        list_url=list_url,
        task_description=task_description,
        detail_visits=detail_visits,
        nav_steps=nav_steps,
        collected_urls=collected_urls,
        common_detail_xpath=common_detail_xpath,
    )
