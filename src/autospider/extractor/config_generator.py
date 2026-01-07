"""配置生成器 - 探索网站并生成爬取配置

此模块负责流程的第一阶段：通过 LLM 探索网站，生成包含导航步骤、
XPath 定位等信息的配置文件 collection_config.json
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_openai import ChatOpenAI

from ..common.config import config
from .llm import LLMDecider
from ..common.storage.persistence import CollectionConfig, ConfigPersistence
from ..common.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from ..extractor.validator.mark_id_validator import MarkIdValidator
from .collector import (
    DetailPageVisit,
    XPathExtractor,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
    smart_scroll,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..common.types import SoMSnapshot


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
        print(f"\n[ConfigGenerator] ===== 开始生成爬取配置 =====")
        print(f"[ConfigGenerator] 任务描述: {self.task_description}")
        print(f"[ConfigGenerator] 列表页: {self.list_url}")
        print(f"[ConfigGenerator] 将探索 {self.explore_count} 个详情页")
        
        # 1. 导航到列表页
        print(f"\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 初始化处理器
        self._initialize_handlers()
        
        # 2. 导航阶段（筛选操作）
        print(f"\n[Phase 2] 导航阶段：根据任务描述进行筛选操作（LLM决策）...")
        nav_success = await self.navigation_handler.run_navigation_phase()
        if not nav_success:
            print(f"[Warning] 导航阶段未能完成筛选，将直接在当前页面探索")
        self.nav_steps = self.navigation_handler.nav_steps
        
        # 3. 探索阶段（进入详情页）
        print(f"\n[Phase 3] 探索阶段：进入 {self.explore_count} 个详情页...")
        await self._explore_phase()
        
        if len(self.detail_visits) < 2:
            print(f"[Warning] 只探索到 {len(self.detail_visits)} 个详情页，需要至少 2 个才能提取模式")
            return self._create_empty_config()
        
        # 3.5 提取公共 xpath
        print(f"\n[Phase 3.5] 提取公共 xpath...")
        self.common_detail_xpath = self.xpath_extractor.extract_common_xpath(self.detail_visits)
        if self.common_detail_xpath:
            print(f"[Phase 3.5] ✓ 提取到公共 xpath: {self.common_detail_xpath}")
        else:
            print(f"[Phase 3.5] ⚠ 未能提取公共 xpath，将使用 LLM 收集")
        
        # 3.6 提取分页控件
        print(f"\n[Phase 3.6] 提取分页控件 xpath...")
        pagination_xpath = await self.pagination_handler.extract_pagination_xpath()
        if pagination_xpath:
            print(f"[Phase 3.6] ✓ 提取到分页控件 xpath: {pagination_xpath}")
        else:
            print(f"[Phase 3.6] ⚠ 未找到分页控件，将只收集当前页")
        
        # 3.6.1 提取跳转控件（用于断点恢复）
        print(f"\n[Phase 3.6.1] 提取跳转控件...")
        jump_widget_xpath = await self.pagination_handler.extract_jump_widget_xpath()
        if jump_widget_xpath:
            print(f"[Phase 3.6.1] ✓ 提取到跳转控件")
        else:
            print(f"[Phase 3.6.1] ⚠ 未找到跳转控件，第二阶段策略不可用")
        
        # 4. 创建并保存配置
        print(f"\n[Phase 4] 保存配置...")
        collection_config = CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=self.common_detail_xpath,
            pagination_xpath=pagination_xpath,
            jump_widget_xpath=jump_widget_xpath,
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)
        
        print(f"\n[Complete] 配置生成完成!")
        print(f"  - 探索了 {len(self.detail_visits)} 个详情页")
        print(f"  - 导航步骤: {len(self.nav_steps)} 个")
        print(f"  - 公共 XPath: {'已提取' if self.common_detail_xpath else '未提取'}")
        print(f"  - 分页控件: {'已提取' if pagination_xpath else '未提取'}")
        print(f"  - 跳转控件: {'已提取' if jump_widget_xpath else '未提取'}")
        
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
    
    async def _explore_phase(self) -> None:
        """探索阶段：进入多个详情页"""
        explored = 0
        max_attempts = self.explore_count * 5
        attempts = 0
        consecutive_bottom_hits = 0
        max_bottom_hits = 3
        
        while explored < self.explore_count and attempts < max_attempts:
            attempts += 1
            print(f"\n[Explore] ===== 尝试 {attempts}/{max_attempts}，已探索 {explored}/{self.explore_count} =====")
            
            # 扫描页面
            print(f"[Explore] 扫描页面...")
            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            
            # 保存截图
            screenshot_path = self.screenshots_dir / f"explore_{attempts:03d}.png"
            screenshot_path.write_bytes(screenshot_bytes)
            print(f"[Explore] 截图已保存: {screenshot_path.name}")
            
            # 使用 LLM 决策
            print(f"[Explore] 调用 LLM 决策...")
            llm_decision = await self.llm_decision_maker.ask_for_decision(snapshot, screenshot_base64)
            
            if llm_decision is None:
                print(f"[Explore] LLM 决策失败，尝试滚动...")
                if await smart_scroll(self.page):
                    consecutive_bottom_hits = 0
                else:
                    consecutive_bottom_hits += 1
                    print(f"[Explore] 已到达页面底部 ({consecutive_bottom_hits}/{max_bottom_hits})")
                    if consecutive_bottom_hits >= max_bottom_hits:
                        print(f"[Explore] ⚠ 连续到达页面底部，停止探索")
                        break
                continue
            
            decision_type = llm_decision.get("action")
            
            # 处理决策结果
            if decision_type == "current_is_detail":
                if await self._handle_current_is_detail(explored):
                    explored += 1
                    consecutive_bottom_hits = 0
                else:
                    if not await smart_scroll(self.page):
                        consecutive_bottom_hits += 1
                        if consecutive_bottom_hits >= max_bottom_hits:
                            break
                    else:
                        consecutive_bottom_hits = 0
                continue
            
            if decision_type == "select_detail_links":
                new_explored = await self._handle_select_detail_links(
                    llm_decision, snapshot, screenshot_base64, explored
                )
                if new_explored > explored:
                    explored = new_explored
                    consecutive_bottom_hits = 0
                else:
                    if not await smart_scroll(self.page):
                        consecutive_bottom_hits += 1
                        if consecutive_bottom_hits >= max_bottom_hits:
                            break
                    else:
                        consecutive_bottom_hits = 0
                continue
            
            if decision_type == "click_to_enter":
                if await self._handle_click_to_enter(llm_decision, snapshot):
                    explored += 1
                    consecutive_bottom_hits = 0
                continue
    
    async def _handle_current_is_detail(self, explored: int) -> bool:
        """处理当前页面就是详情页的情况"""
        current_url = self.page.url
        if current_url not in self.visited_detail_urls:
            print(f"[Explore] ✓ LLM 判断当前页面就是详情页: {current_url[:60]}...")
            
            visit = DetailPageVisit(
                list_page_url=self.list_url,
                detail_page_url=current_url,
                clicked_element_mark_id=0,
                clicked_element_tag="page",
                clicked_element_text="当前页面",
                clicked_element_href=current_url,
                clicked_element_role="page",
                clicked_element_xpath_candidates=[],
                step_index=self.step_index,
                timestamp=datetime.now().isoformat(),
            )
            self.detail_visits.append(visit)
            self.visited_detail_urls.add(current_url)
            self.step_index += 1
            print(f"[Explore] 已探索 {explored + 1}/{self.explore_count} 个详情页")
            
            # 返回列表页
            print(f"[Explore] 返回列表页...")
            await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
            return True
        return False
    
    async def _handle_select_detail_links(
        self, llm_decision: dict, snapshot: "SoMSnapshot", screenshot_base64: str, explored: int
    ) -> int:
        """处理选择详情链接的情况"""
        reasoning = llm_decision.get("reasoning", "")
        mark_id_text_map = llm_decision.get("mark_id_text_map", {})
        old_mark_ids = llm_decision.get("mark_ids", [])
        
        mark_ids = []
        
        if mark_id_text_map:
            print(f"[Explore] LLM 返回了 {len(mark_id_text_map)} 个 mark_id-文本映射")
            
            # 验证 mark_id
            if config.url_collector.validate_mark_id:
                mark_ids = self._validate_mark_ids(mark_id_text_map, snapshot, screenshot_base64)
                if not mark_ids:
                    return explored
            else:
                mark_ids = [int(k) for k in mark_id_text_map.keys()]
        elif old_mark_ids:
            print(f"[Explore] LLM 使用旧格式返回了 {len(old_mark_ids)} 个 mark_ids")
            mark_ids = old_mark_ids
        
        if not mark_ids:
            print(f"[Explore] 没有选中任何链接")
            return explored
        
        print(f"[Explore] 理由: {reasoning[:100]}...")
        
        # 获取候选元素
        candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
        print(f"[Explore] 找到 {len(candidates)} 个候选元素")
        
        # 遍历候选，提取 URL
        for i, candidate in enumerate(candidates, 1):
            if explored >= self.explore_count:
                break
            
            print(f"[Explore] 处理候选 {i}/{len(candidates)}: [{candidate.mark_id}] {candidate.text[:30]}...")
            url = await self.url_extractor.extract_from_element(candidate, snapshot)
            
            if url and url not in self.visited_detail_urls:
                visit = DetailPageVisit(
                    list_page_url=self.list_url,
                    detail_page_url=url,
                    clicked_element_mark_id=candidate.mark_id,
                    clicked_element_tag=candidate.tag,
                    clicked_element_text=candidate.text,
                    clicked_element_href=candidate.href,
                    clicked_element_role=candidate.role,
                    clicked_element_xpath_candidates=[
                        {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                        for c in candidate.xpath_candidates
                    ],
                    step_index=self.step_index,
                    timestamp=datetime.now().isoformat(),
                )
                self.detail_visits.append(visit)
                self.visited_detail_urls.add(url)
                explored += 1
                self.step_index += 1
                print(f"[Explore] ✓ 获取到详情页 URL: {url[:60]}...")
                print(f"[Explore] 已探索 {explored}/{self.explore_count} 个详情页")
        
        return explored
    
    def _validate_mark_ids(
        self, mark_id_text_map: dict, snapshot: "SoMSnapshot", screenshot_base64: str
    ) -> list[int]:
        """验证 mark_id 与文本的匹配"""
        validator = MarkIdValidator()
        valid_mark_ids, validation_results = validator.validate_mark_id_text_map(
            mark_id_text_map, snapshot
        )
        
        total = len(validation_results)
        passed = len([r for r in validation_results if r.is_valid])
        failed_results = [r for r in validation_results if not r.is_valid]
        print(f"[Explore] mark_id 验证: {passed}/{total} 通过")
        
        # 如果有验证失败且没有通过的，重试
        if failed_results and not valid_mark_ids:
            print(f"[Explore] ⚠ 所有 mark_id 验证失败，将反馈给 LLM 重新选择")
            return []
        
        return valid_mark_ids
    
    async def _handle_click_to_enter(self, llm_decision: dict, snapshot: "SoMSnapshot") -> bool:
        """处理点击进入详情页的情况"""
        mark_id = llm_decision.get("mark_id")
        print(f"[Explore] LLM 要求点击元素 [{mark_id}] 进入详情页")
        
        element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
        if element:
            url = await self.url_extractor.click_and_get_url(element)
            if url and url not in self.visited_detail_urls:
                visit = DetailPageVisit(
                    list_page_url=self.list_url,
                    detail_page_url=url,
                    clicked_element_mark_id=element.mark_id,
                    clicked_element_tag=element.tag,
                    clicked_element_text=element.text,
                    clicked_element_href=element.href,
                    clicked_element_role=element.role,
                    clicked_element_xpath_candidates=[
                        {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                        for c in element.xpath_candidates
                    ],
                    step_index=self.step_index,
                    timestamp=datetime.now().isoformat(),
                )
                self.detail_visits.append(visit)
                self.visited_detail_urls.add(url)
                self.step_index += 1
                print(f"[Explore] ✓ 获取到详情页 URL")
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
    )
    return await generator.generate_config()
