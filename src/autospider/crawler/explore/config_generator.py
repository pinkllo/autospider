"""配置生成器 - 探索网站并生成爬取配置

此模块负责流程的第一阶段：通过 LLM 探索网站，生成包含导航步骤、
XPath 定位等信息的配置文件 collection_config.json
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from ...common.config import config
from ...common.experience import SkillRuntime
from ...common.logger import get_logger
from ...common.llm import LLMDecider
from ...common.storage.collection_persistence import CollectionConfig, ConfigPersistence
from ..collector import (
    XPathExtractor,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
)
from .shared_workflow import (
    build_detail_visit,
    extract_mark_id_text_map,
    prepare_explore_skill_context,
    resolve_click_mark_id,
    resolve_selected_mark_ids,
    run_detail_explore_loop,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ...common.types import SoMSnapshot


logger = get_logger(__name__)


class ConfigGenerator:
    """配置生成器

    通过探索网站生成爬取配置文件，包括：
    - 导航步骤（筛选操作）
    - 详情页 XPath 定位
    - 分页控件 XPath
    - 跳转控件 XPath（用于断点恢复）
    """

    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        explore_count: int = 3,
        max_nav_steps: int = 10,
        output_dir: str = "output",
        skill_runtime: SkillRuntime | None = None,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
    ):
        """初始化配置生成器

        Args:
            page: Playwright 页面对象
            list_url: 列表页 URL
            task_description: 任务描述
            explore_count: 探索详情页的数量
            max_nav_steps: 最大导航步骤数
            output_dir: 输出目录
        """
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.explore_count = explore_count
        self.max_nav_steps = max_nav_steps
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.skill_runtime = skill_runtime or SkillRuntime()
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])

        # 截图目录
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 数据收集
        self.detail_visits: list[DetailPageVisit] = []
        self.visited_detail_urls: set[str] = set()
        self.step_index = 0

        # 生成的配置
        self.nav_steps: list[dict] = []
        self.common_detail_xpath: str | None = None

        # LLM 决策器
        self.decider = LLMDecider()

        # 处理器（延迟初始化）
        self.xpath_extractor = XPathExtractor()
        self.url_extractor = URLExtractor(page, list_url)
        self.llm_decision_maker: LLMDecisionMaker | None = None
        self.navigation_handler: NavigationHandler | None = None
        self.pagination_handler: PaginationHandler | None = None

        # 配置持久化
        self.config_persistence = ConfigPersistence(config_dir=output_dir)

    async def generate_config(self) -> CollectionConfig:
        """生成配置文件（主流程）

        Returns:
            生成的配置对象
        """
        logger.info("\n[ConfigGenerator] ===== 开始生成爬取配置 =====")
        logger.info(f"[ConfigGenerator] 任务描述: {self.task_description}")
        logger.info(f"[ConfigGenerator] 列表页: {self.list_url}")
        logger.info(f"[ConfigGenerator] 将探索 {self.explore_count} 个详情页")
        await self._prepare_skill_context()

        # 1. 导航到列表页
        logger.info("\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

        # 初始化处理器
        self._initialize_handlers()

        # 2. 导航阶段（筛选操作）
        logger.info("\n[Phase 2] 导航阶段：根据任务描述进行筛选操作（LLM决策）...")
        nav_success = await self.navigation_handler.run_navigation_phase()
        if not nav_success:
            logger.info("[Warning] 导航阶段未能完成筛选，将直接在当前页面探索")
        self.nav_steps = self.navigation_handler.nav_steps

        if self.navigation_handler and self.navigation_handler.page is not self.page:
            new_page = self.navigation_handler.page
            new_list_url = self.navigation_handler.list_url or new_page.url
            self._sync_page_references(new_page, list_url=new_list_url)

        # 3. 探索阶段（进入详情页）
        logger.info(f"\n[Phase 3] 探索阶段：进入 {self.explore_count} 个详情页...")
        await self._explore_phase()

        if len(self.detail_visits) < 2:
            logger.info(
                f"[Warning] 只探索到 {len(self.detail_visits)} 个详情页，需要至少 2 个才能提取模式"
            )
            return self._create_empty_config()

        # 3.5 提取公共 xpath
        logger.info("\n[Phase 3.5] 提取公共 xpath...")
        self.common_detail_xpath = self.xpath_extractor.extract_common_xpath(self.detail_visits)
        if self.common_detail_xpath:
            logger.info(f"[Phase 3.5] ✓ 提取到公共 xpath: {self.common_detail_xpath}")
        else:
            logger.info("[Phase 3.5] ⚠ 未能提取公共 xpath，将使用 LLM 收集")

        # 3.6 提取分页控件
        logger.info("\n[Phase 3.6] 提取分页控件 xpath...")
        pagination_xpath = await self.pagination_handler.extract_pagination_xpath()
        if pagination_xpath:
            logger.info(f"[Phase 3.6] ✓ 提取到分页控件 xpath: {pagination_xpath}")
        else:
            logger.info("[Phase 3.6] ⚠ 未找到分页控件，将只收集当前页")

        # 3.6.1 提取跳转控件（用于断点恢复）
        logger.info("\n[Phase 3.6.1] 提取跳转控件...")
        jump_widget_xpath = await self.pagination_handler.extract_jump_widget_xpath()
        if jump_widget_xpath:
            logger.info("[Phase 3.6.1] ✓ 提取到跳转控件")
        else:
            logger.info("[Phase 3.6.1] ⚠ 未找到跳转控件，第二阶段策略不可用")

        # 4. 创建并保存配置
        logger.info("\n[Phase 4] 保存配置...")
        collection_config = CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=self.common_detail_xpath,
            pagination_xpath=pagination_xpath,
            jump_widget_xpath=jump_widget_xpath,
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)

        logger.info("\n[Complete] 配置生成完成!")
        logger.info(f"  - 探索了 {len(self.detail_visits)} 个详情页")
        logger.info(f"  - 导航步骤: {len(self.nav_steps)} 个")
        logger.info(f"  - 公共 XPath: {'已提取' if self.common_detail_xpath else '未提取'}")
        logger.info(f"  - 分页控件: {'已提取' if pagination_xpath else '未提取'}")
        logger.info(f"  - 跳转控件: {'已提取' if jump_widget_xpath else '未提取'}")

        return collection_config

    def _initialize_handlers(self):
        """初始化各个处理器"""
        self.llm_decision_maker = LLMDecisionMaker(
            page=self.page,
            decider=self.decider,
            task_description=self.task_description,
            collected_urls=[],
            visited_detail_urls=self.visited_detail_urls,
            list_url=self.list_url,
            selected_skills_context=self.selected_skills_context,
            selected_skills=self.selected_skills,
        )

        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=self.max_nav_steps,
            decider=self.decider,
            screenshots_dir=self.screenshots_dir,
        )

        self.pagination_handler = PaginationHandler(
            page=self.page,
            list_url=self.list_url,
            screenshots_dir=self.screenshots_dir,
            llm_decision_maker=self.llm_decision_maker,
        )

    def _sync_page_references(self, page: "Page", list_url: str | None = None) -> None:
        """同步页面引用到各处理器"""
        self.page = page
        if list_url:
            self.list_url = list_url

        if self.url_extractor:
            self.url_extractor.page = page
            if list_url:
                self.url_extractor.list_url = list_url
        if self.llm_decision_maker:
            self.llm_decision_maker.page = page
            if list_url:
                self.llm_decision_maker.list_url = list_url
        if self.navigation_handler:
            self.navigation_handler.page = page
            if list_url:
                self.navigation_handler.list_url = list_url
        if self.pagination_handler:
            self.pagination_handler.page = page
            if list_url:
                self.pagination_handler.list_url = list_url

    async def _prepare_skill_context(self) -> None:
        self.selected_skills, self.selected_skills_context = await prepare_explore_skill_context(
            skill_runtime=self.skill_runtime,
            phase="url_collector",
            url=self.list_url,
            task_context={
                "task_description": self.task_description,
                "mode": "generate_config",
            },
            llm=self.decider.llm,
            preselected_skills=self.selected_skills,
        )

    async def _explore_phase(self) -> None:
        await run_detail_explore_loop(
            page=self.page,
            screenshots_dir=self.screenshots_dir,
            llm_decision_maker=self.llm_decision_maker,
            explore_count=self.explore_count,
            on_current_detail=self._handle_current_is_detail,
            on_select_detail_links=self._handle_select_detail_links,
            on_click_to_enter=self._handle_click_to_enter,
        )

    async def _handle_current_is_detail(self, explored: int) -> bool:
        """处理当前页面就是详情页的情况"""
        current_url = self.page.url
        if current_url not in self.visited_detail_urls:
            logger.info(f"[Explore] ✓ LLM 判断当前页面就是详情页: {current_url[:60]}...")
            visit = build_detail_visit(
                list_url=self.list_url,
                detail_url=current_url,
                step_index=self.step_index,
            )
            self.detail_visits.append(visit)
            self.visited_detail_urls.add(current_url)
            self.step_index += 1
            logger.info(f"[Explore] 已探索 {explored + 1}/{self.explore_count} 个详情页")

            # 返回列表页
            logger.info("[Explore] 返回列表页...")
            await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
            return True
        return False

    async def _handle_select_detail_links(
        self, llm_decision: dict, snapshot: "SoMSnapshot", screenshot_base64: str, explored: int
    ) -> int:
        """处理选择详情链接的情况"""
        args = llm_decision.get("args") if isinstance(llm_decision.get("args"), dict) else {}
        reasoning = llm_decision.get("thinking") or ""
        items = args.get("items") or []
        mark_id_text_map = extract_mark_id_text_map(items)
        if not mark_id_text_map:
            mark_id_text_map = args.get("mark_id_text_map", {}) or {}
        old_mark_ids = args.get("mark_ids", [])
        mark_ids = await resolve_selected_mark_ids(
            page=self.page,
            llm=self.decider.llm,
            snapshot=snapshot,
            mark_id_text_map=mark_id_text_map,
            fallback_mark_ids=old_mark_ids,
        )

        if not mark_ids:
            logger.info("[Explore] 没有选中任何链接")
            return explored

        if reasoning:
            logger.info(f"[Explore] 理由: {reasoning[:100]}...")

        # 获取候选元素
        candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
        logger.info(f"[Explore] 找到 {len(candidates)} 个候选元素")

        # 遍历候选，提取 URL
        for i, candidate in enumerate(candidates, 1):
            if explored >= self.explore_count:
                break

            logger.info(
                f"[Explore] 处理候选 {i}/{len(candidates)}: [{candidate.mark_id}] {candidate.text[:30]}..."
            )
            url = await self.url_extractor.extract_from_element(
                candidate, snapshot, nav_steps=self.nav_steps
            )

            if url and url not in self.visited_detail_urls:
                visit = build_detail_visit(
                    list_url=self.list_url,
                    detail_url=url,
                    step_index=self.step_index,
                    element=candidate,
                )
                self.detail_visits.append(visit)
                self.visited_detail_urls.add(url)
                explored += 1
                self.step_index += 1
                logger.info(f"[Explore] ✓ 获取到详情页 URL: {url[:60]}...")
                logger.info(f"[Explore] 已探索 {explored}/{self.explore_count} 个详情页")

        return explored

    async def _handle_click_to_enter(self, llm_decision: dict, snapshot: "SoMSnapshot") -> bool:
        """处理点击进入详情页的情况"""
        args = llm_decision.get("args") if isinstance(llm_decision.get("args"), dict) else {}
        mark_id_raw = args.get("mark_id")
        target_text = args.get("target_text") or ""
        logger.info(f"[Explore] LLM 要求点击元素 [{mark_id_raw}] 进入详情页")
        mark_id = await resolve_click_mark_id(
            page=self.page,
            llm=self.decider.llm,
            snapshot=snapshot,
            raw_mark_id=mark_id_raw,
            target_text=target_text,
        )

        element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
        if element:
            url = await self.url_extractor.click_and_get_url(
                element, snapshot, nav_steps=self.nav_steps
            )
            if url and url not in self.visited_detail_urls:
                visit = build_detail_visit(
                    list_url=self.list_url,
                    detail_url=url,
                    step_index=self.step_index,
                    element=element,
                )
                self.detail_visits.append(visit)
                self.visited_detail_urls.add(url)
                self.step_index += 1
                logger.info("[Explore] ✓ 获取到详情页 URL")
                return True
        return False

    def _create_empty_config(self) -> CollectionConfig:
        """创建空配置（探索失败时）"""
        return CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=None,
            pagination_xpath=None,
            jump_widget_xpath=None,
            list_url=self.list_url,
            task_description=self.task_description,
        )


# 便捷函数
async def generate_collection_config(
    page: "Page",
    list_url: str,
    task_description: str,
    explore_count: int = 3,
    output_dir: str = "output",
    persist_progress: bool = True,
    skill_runtime: SkillRuntime | None = None,
    selected_skills: list[dict] | None = None,
) -> CollectionConfig:
    """生成爬取配置的便捷函数

    Args:
        page: Playwright 页面对象
        list_url: 列表页 URL
        task_description: 任务描述
        explore_count: 探索详情页的数量
        output_dir: 输出目录

    Returns:
        生成的配置对象
    """
    generator = ConfigGenerator(
        page=page,
        list_url=list_url,
        task_description=task_description,
        explore_count=explore_count,
        output_dir=output_dir,
        skill_runtime=skill_runtime,
        selected_skills=selected_skills,
    )
    return await generator.generate_config()
