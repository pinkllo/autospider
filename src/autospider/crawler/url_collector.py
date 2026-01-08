"""详情页 URL 收集器（重构版）

实现流程:
1. 探索阶段：进入 N 个不同的详情页，记录每次进入的操作步骤
2. 分析阶段：分析这 N 次操作的共同模式，提取公共脚本
3. 收集阶段：使用公共脚本遍历列表页，收集所有详情页的 URL
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_openai import ChatOpenAI

from ..common.config import config
from ..common.logger import get_logger
from ..common.storage.redis_manager import RedisManager
from ..extractor.llm.decider import LLMDecider
from ..extractor.llm.prompt_template import render_template
from ..common.storage.persistence import CollectionConfig, ConfigPersistence, ProgressPersistence, CollectionProgress
from ..extractor.output.script_generator import ScriptGenerator
from .checkpoint.rate_controller import AdaptiveRateController
from .checkpoint.resume_strategy import ResumeCoordinator
from ..common.som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    format_marks_for_llm,
    inject_and_scan,
)
from ..extractor.validator.mark_id_validator import MarkIdValidator
from ..extractor.collector import (
    DetailPageVisit,
    URLCollectorResult,
    XPathExtractor,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
    smart_scroll,
)
from .base_collector import BaseCollector

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..common.types import SoMSnapshot

# 日志器
logger = get_logger(__name__)

# Prompt 模板文件路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent.parent.parent.parent / "prompts" / "url_collector.yaml")


class URLCollector(BaseCollector):
    """详情页 URL 收集器（协调器）
    
    继承 BaseCollector，增加探索阶段功能。
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
        # 调用基类初始化
        super().__init__(
            page=page,
            list_url=list_url,
            task_description=task_description,
            output_dir=output_dir,
        )
        
        self.explore_count = explore_count
        self.max_nav_steps = max_nav_steps
        
        # 探索阶段特有状态
        self.detail_visits: list[DetailPageVisit] = []
        self.step_index = 0
        self.visited_detail_urls: set[str] = set()
        
        # 初始化额外组件
        self.decider = LLMDecider()
        self.script_generator = ScriptGenerator(output_dir)
        self.config_persistence = ConfigPersistence(output_dir)
        self.xpath_extractor = XPathExtractor()
        
        # LLM（用于决策）
        self.llm = ChatOpenAI(
            api_key=config.llm.planner_api_key or config.llm.api_key,
            base_url=config.llm.planner_api_base or config.llm.api_base,
            model=config.llm.planner_model or config.llm.model,
            temperature=0.1,
            max_tokens=4096,
        )
    
    async def run(self) -> URLCollectorResult:
        """运行 URL 收集流程"""
        print(f"\n[URLCollector] ===== 开始收集详情页 URL =====")
        print(f"[URLCollector] 任务描述: {self.task_description}")
        print(f"[URLCollector] 列表页: {self.list_url}")
        print(f"[URLCollector] 将探索 {self.explore_count} 个详情页")
        
        # 0.5 加载历史进度和配置信息
        previous_progress = self.progress_persistence.load_progress()
        previous_config = self.config_persistence.load()
        target_page_num = 1  # 默认从第1页开始
        is_resume = False  # 是否是断点恢复
        config_mismatch = False
        progress_mismatch = False

        # 校验历史配置是否与当前任务匹配
        if previous_config:
            if previous_config.list_url and previous_config.list_url != self.list_url:
                config_mismatch = True
            if (
                previous_config.task_description
                and previous_config.task_description != self.task_description
            ):
                config_mismatch = True
            if config_mismatch:
                print(
                    f"[断点恢复] 历史配置与当前任务不匹配，忽略旧配置与进度"
                )
                previous_config = None
                previous_progress = None

        # 校验历史进度是否与当前任务匹配
        if previous_progress and not self._is_progress_compatible(previous_progress):
            print(f"[断点恢复] 历史进度与当前任务不匹配，忽略旧进度")
            previous_progress = None
            progress_mismatch = True

        # 0.6 连接 Redis / 本地文件并加载历史 URL（断点续爬）
        if not config_mismatch and not progress_mismatch:
            await self._load_previous_urls()
            if self.collected_urls:
                self.visited_detail_urls.update(self.collected_urls)
        
        if previous_progress and previous_progress.current_page_num > 1:
            print(f"\n[断点恢复] 检测到上次中断在第 {previous_progress.current_page_num} 页")
            print(f"[断点恢复] 已收集 {previous_progress.collected_count} 个 URL")
            target_page_num = previous_progress.current_page_num
            is_resume = True
            
            # 恢复速率控制器状态
            self.rate_controller.current_level = previous_progress.backoff_level
            self.rate_controller.consecutive_success_count = previous_progress.consecutive_success_pages
            print(f"[断点恢复] 恢复速率控制状态: 等级={previous_progress.backoff_level}, 连续成功={previous_progress.consecutive_success_pages}")
        
        # 加载历史配置（导航步骤、XPath等）
        if previous_config:
            if previous_config.nav_steps:
                self.nav_steps = previous_config.nav_steps
                print(f"[断点恢复] 已加载 {len(self.nav_steps)} 个导航步骤")
            if previous_config.common_detail_xpath:
                self.common_detail_xpath = previous_config.common_detail_xpath
                print(f"[断点恢复] 已加载公共详情页 XPath")
        
        # 1. 导航到列表页
        print(f"\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 初始化延迟组件
        self._initialize_handlers()
        
        # 2. 导航阶段
        if is_resume and self.nav_steps:
            # 断点恢复：直接重放已保存的导航步骤，无需LLM决策
            print(f"\n[Phase 2] 导航阶段：重放已保存的 {len(self.nav_steps)} 个导航步骤（跳过LLM决策）...")
            nav_success = await self.navigation_handler.replay_nav_steps(self.nav_steps)
            if not nav_success:
                print(f"[Warning] 导航步骤重放失败，将直接在当前页面探索")
        else:
            # 首次运行：让LLM进行决策并保存导航步骤
            print(f"\n[Phase 2] 导航阶段：根据任务描述进行筛选操作（LLM决策）...")
            nav_success = await self.navigation_handler.run_navigation_phase()
            if not nav_success:
                print(f"[Warning] 导航阶段未能完成筛选，将直接在当前页面探索")
            # 保存导航步骤
            self.nav_steps = self.navigation_handler.nav_steps
        
        # 3. 探索阶段
        if is_resume and self.common_detail_xpath:
            # 断点恢复且已有 common_detail_xpath：跳过探索阶段
            print(f"\n[Phase 3] 探索阶段：跳过（已有公共 XPath）")
            print(f"[Phase 3] 使用已保存的公共详情页 XPath: {self.common_detail_xpath}")
        else:
            # 首次运行：需要探索并提取 XPath
            print(f"\n[Phase 3] 探索阶段：进入 {self.explore_count} 个详情页...")
            await self._explore_phase()
            
            if len(self.detail_visits) < 2:
                print(f"[Warning] 只探索到 {len(self.detail_visits)} 个详情页，需要至少 2 个才能提取模式")
                return self._create_result()
            
            # 3.5 提取公共 xpath
            print(f"\n[Phase 3.5] 提取公共 xpath...")
            self.common_detail_xpath = self.xpath_extractor.extract_common_xpath(self.detail_visits)
            if self.common_detail_xpath:
                print(f"[Phase 3.5] ✓ 提取到公共 xpath: {self.common_detail_xpath}")
            else:
                print(f"[Phase 3.5] ⚠ 未能提取公共 xpath，将使用 LLM 收集")
        
        # 3.6 提取分页控件
        if is_resume and previous_config and previous_config.pagination_xpath:
            # 断点恢复：使用已保存的分页控件 XPath
            pagination_xpath = previous_config.pagination_xpath
            self.pagination_handler.pagination_xpath = pagination_xpath
            print(f"\n[Phase 3.6] 提取分页控件 xpath：使用已保存配置")
            print(f"[Phase 3.6] ✓ 分页控件 xpath: {pagination_xpath}")
        else:
            # 首次运行：提取分页控件 XPath
            print(f"\n[Phase 3.6] 提取分页控件 xpath...")
            pagination_xpath = await self.pagination_handler.extract_pagination_xpath()
            if pagination_xpath:
                print(f"[Phase 3.6] ✓ 提取到分页控件 xpath: {pagination_xpath}")
            else:
                print(f"[Phase 3.6] ⚠ 未找到分页控件，将只收集当前页")
        
        # 3.6.1 提取跳转控件（用于断点恢复第二阶段）
        if is_resume and previous_config and previous_config.jump_widget_xpath:
            # 断点恢复：使用已保存的跳转控件 XPath
            jump_widget_xpath = previous_config.jump_widget_xpath
            self.pagination_handler.jump_widget_xpath = jump_widget_xpath
            print(f"\n[Phase 3.6.1] 提取跳转控件：使用已保存配置")
            print(f"[Phase 3.6.1] ✓ 跳转控件已加载")
        else:
            # 首次运行：提取跳转控件 XPath
            print(f"\n[Phase 3.6.1] 提取跳转控件...")
            jump_widget_xpath = await self.pagination_handler.extract_jump_widget_xpath()
            if jump_widget_xpath:
                print(f"[Phase 3.6.1] ✓ 提取到跳转控件")
            else:
                print(f"[Phase 3.6.1] ⚠ 未找到跳转控件，第二阶段策略不可用")
        
        # 3.7 断点恢复：跳转到目标页
        if target_page_num > 1:
            print(f"\n[Phase 3.7] 断点恢复：尝试跳转到第 {target_page_num} 页...")
            actual_page = await self._resume_to_target_page(
                target_page_num=target_page_num,
                jump_widget_xpath=jump_widget_xpath,
                pagination_xpath=pagination_xpath
            )
            # 更新分页处理器的当前页码
            self.pagination_handler.current_page_num = actual_page
            print(f"[Phase 3.7] ✓ 已定位到第 {actual_page} 页，继续收集")
        
        # 4. 收集阶段
        if self.common_detail_xpath:
            print(f"\n[Phase 4] 收集阶段：使用公共 xpath 遍历列表页...")
            await self._collect_phase_with_xpath()
        else:
            print(f"\n[Phase 4] 收集阶段：LLM 遍历列表页...")
            await self._collect_phase_with_llm()
        
        # 4.5 持久化配置
        print(f"\n[Phase 4.5] 持久化配置...")
        self._save_config()
        
        # 5. 生成爬虫脚本
        print(f"\n[Phase 5] 生成爬虫脚本...")
        crawler_script = await self._generate_crawler_script()
        
        # 6. 保存结果
        result = self._create_result()
        print(f"\n[Complete] 收集完成!")
        print(f"  - 探索了 {len(self.detail_visits)} 个详情页")
        print(f"  - 收集到 {len(self.collected_urls)} 个详情页 URL")
        
        await self._save_result(result, crawler_script)
        
        return result
    
    def _initialize_handlers(self) -> None:
        """初始化各个处理器（覆盖基类方法，添加探索阶段所需组件）"""
        # 先初始化 LLM 决策器（需要在基类初始化之前，因为 pagination_handler 依赖它）
        self.llm_decision_maker = LLMDecisionMaker(
            page=self.page,
            decider=self.decider,
            task_description=self.task_description,
            collected_urls=self.collected_urls,
            visited_detail_urls=self.visited_detail_urls,
            list_url=self.list_url,
        )
        
        # 调用基类初始化（初始化 url_extractor 和 pagination_handler）
        super()._initialize_handlers()
        
        # URLCollector 特有的 NavigationHandler
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=self.max_nav_steps,
            decider=self.decider,
            screenshots_dir=self.screenshots_dir,
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
            if self.nav_steps:
                await self.navigation_handler.replay_nav_steps(self.nav_steps)
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
            url = await self.url_extractor.extract_from_element(
                candidate, snapshot, nav_steps=self.nav_steps
            )
            
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
            # 这里可以实现重试逻辑，为简化暂时跳过
            return []
        
        return valid_mark_ids
    
    async def _handle_click_to_enter(self, llm_decision: dict, snapshot: "SoMSnapshot") -> bool:
        """处理点击进入详情页的情况"""
        mark_id = llm_decision.get("mark_id")
        print(f"[Explore] LLM 要求点击元素 [{mark_id}] 进入详情页")
        
        element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
        if element:
            url = await self.url_extractor.click_and_get_url(
                element, nav_steps=self.nav_steps
            )
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
    
    async def _resume_to_target_page(
        self,
        target_page_num: int,
        jump_widget_xpath: dict[str, str] | None = None,
        pagination_xpath: str | None = None
    ) -> int:
        """使用三阶段策略恢复到目标页
        
        Args:
            target_page_num: 目标页码
            jump_widget_xpath: 跳转控件xpath（用于第二阶段）
            pagination_xpath: 分页控件xpath（用于第三阶段）
            
        Returns:
            实际到达的页码
        """
        # 组装恢复协调器
        coordinator = ResumeCoordinator(
            list_url=self.list_url,
            collected_urls=set(self.collected_urls),
            jump_widget_xpath=jump_widget_xpath,
            detail_xpath=self.common_detail_xpath,
            pagination_xpath=pagination_xpath,
        )
        
        # 执行恢复
        actual_page = await coordinator.resume_to_page(self.page, target_page_num)
        
        return actual_page
    
    async def _collect_phase_with_xpath(self) -> None:
        """收集阶段：使用公共 xpath 直接提取 URL"""
        if not self.common_detail_xpath:
            return
        
        # 返回列表页
        print(f"[Collect] 返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 重放导航步骤
        if self.nav_steps:
            await self.navigation_handler.replay_nav_steps(self.nav_steps)
        
        max_pages = config.url_collector.max_pages
        target_url_count = config.url_collector.target_url_count
        
        print(f"[Collect] 目标：收集 {target_url_count} 个 URL")
        print(f"[Collect] 最大翻页次数: {max_pages}")
        
        # 翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            print(f"\n[Collect] ===== 第 {self.pagination_handler.current_page_num} 页 =====")
            
            if len(self.collected_urls) >= target_url_count:
                print(f"[Collect] ✓ 已达到目标数量 {target_url_count}")
                break
            
            # 应用速率控制延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                print(f"[速率控制] 等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)
            
            # 使用 xpath 提取 URL
            page_success = False
            urls_before = len(self.collected_urls)
            
            try:
                locators = self.page.locator(f"xpath={self.common_detail_xpath}")
                count = await locators.count()
                print(f"[Collect-XPath] 找到 {count} 个匹配元素")
                
                for i in range(count):
                    if len(self.collected_urls) >= target_url_count:
                        break
                    
                    locator = locators.nth(i)
                    
                    # 尝试从 href 获取
                    try:
                        href = await locator.get_attribute("href")
                        if href:
                            from urllib.parse import urljoin
                            url = urljoin(self.list_url, href)
                            if url not in self.collected_urls:
                                self.collected_urls.append(url)
                                if self.redis_manager:
                                    await self.redis_manager.save_item(url)
                                print(f"[Collect-XPath] ✓ [{i+1}/{count}] {url[:60]}...")
                            continue
                    except Exception as e:
                        print(f"[Collect-XPath] 获取 href 失败: {e}")
                    
                    # 点击获取
                    url = await self.url_extractor.click_element_and_get_url(locator, self.nav_steps)
                    if url and url not in self.collected_urls:
                        self.collected_urls.append(url)
                        if self.redis_manager:
                            await self.redis_manager.save_item(url)
                        print(f"[Collect-XPath] ✓ [{i+1}/{count}] {url[:60]}...")
                
                # 如果成功收集到URL，标记为成功
                if len(self.collected_urls) > urls_before:
                    page_success = True
            
            except Exception as e:
                print(f"[Collect-XPath] 提取失败: {e}")
                # 应用惩罚
                self.rate_controller.apply_penalty()
            
            # 记录成功
            if page_success:
                self.rate_controller.record_success()
            
            # 保存进度
            self._save_progress()
            
            # 翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                print(f"[Collect] 无法翻页，结束收集")
                break
        
        print(f"\n[Collect] 收集完成! 共收集 {len(self.collected_urls)} 个 URL")
    
    async def _collect_phase_with_llm(self) -> None:
        """收集阶段：使用 LLM 遍历列表页"""
        # 返回列表页
        print(f"[Collect] 返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        target_url_count = config.url_collector.target_url_count
        max_pages = config.url_collector.max_pages
        
        print(f"[Collect] 目标：收集 {target_url_count} 个 URL")
        print(f"[Collect] 最大翻页次数: {max_pages}")
        
        # 翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            print(f"\n[Collect] ===== 第 {self.pagination_handler.current_page_num} 页 =====")
            
            if len(self.collected_urls) >= target_url_count:
                print(f"[Collect] ✓ 已达到目标数量")
                break
            
            # 应用速率控制延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                print(f"[速率控制] 等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)
            
            scroll_count = 0
            last_url_count = len(self.collected_urls)
            no_new_urls_count = 0
            page_success = False
            
            # 滚动收集
            try:
                while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
                    if len(self.collected_urls) >= target_url_count:
                        break
                    
                    print(f"\n[Collect] ----- 第 {self.pagination_handler.current_page_num} 页，滚动 {scroll_count + 1}/{max_scrolls} -----")
                    
                    # 扫描页面
                    await clear_overlay(self.page)
                    snapshot = await inject_and_scan(self.page)
                    screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                    
                    # LLM 识别
                    llm_decision = await self.llm_decision_maker.ask_for_decision(snapshot, screenshot_base64)
                    
                    if llm_decision and llm_decision.get("action") == "select_detail_links":
                        mark_id_text_map = llm_decision.get("mark_id_text_map", {})
                        old_mark_ids = llm_decision.get("mark_ids", [])
                        mark_ids: list[int] = []

                        if mark_id_text_map:
                            if config.url_collector.validate_mark_id:
                                mark_ids = self._validate_mark_ids(
                                    mark_id_text_map, snapshot, screenshot_base64
                                )
                            else:
                                mark_ids = [int(k) for k in mark_id_text_map.keys()]
                        elif old_mark_ids:
                            mark_ids = old_mark_ids

                        print(f"[Collect] LLM 识别到 {len(mark_ids)} 个详情链接")
                        
                        candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                        
                        for candidate in candidates:
                            url = await self.url_extractor.extract_from_element(
                                candidate, snapshot, nav_steps=self.nav_steps
                            )
                            if url and url not in self.collected_urls:
                                self.collected_urls.append(url)
                                if self.redis_manager:
                                    await self.redis_manager.save_item(url)
                    
                    # 检查是否有新 URL
                    current_count = len(self.collected_urls)
                    if current_count == last_url_count:
                        no_new_urls_count += 1
                        print(f"[Collect] 连续 {no_new_urls_count} 次无新 URL")
                    else:
                        no_new_urls_count = 0
                        print(f"[Collect] ✓ 当前已收集 {current_count} 个 URL")
                        last_url_count = current_count
                        page_success = True
                    
                    # 滚动
                    if not await smart_scroll(self.page):
                        print(f"[Collect] 已到达页面底部")
                        break
                    scroll_count += 1
                
            except Exception as e:
                print(f"[Collect-LLM] 收集过程出错: {e}")
                # 应用惩罚
                self.rate_controller.apply_penalty()
            
            # 记录成功
            if page_success:
                self.rate_controller.record_success()
            
            # 保存进度
            self._save_progress()
            
            # 翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                print(f"[Collect] 无法翻页，结束收集")
                break
        
        print(f"\n[Collect] 收集完成! 共收集 {len(self.collected_urls)} 个 URL")
    
    def _save_config(self):
        """保存配置"""
        collection_config = CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=self.common_detail_xpath,
            pagination_xpath=self.pagination_handler.pagination_xpath if self.pagination_handler else None,
            jump_widget_xpath=self.pagination_handler.jump_widget_xpath if self.pagination_handler else None,
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)
        print(f"[Phase 4.5] ✓ 配置已持久化")
    
    def _save_progress(self):
        """保存收集进度"""
        progress = CollectionProgress(
            status="RUNNING",
            list_url=self.list_url,
            task_description=self.task_description,
            current_page_num=self.pagination_handler.current_page_num if self.pagination_handler else 1,
            collected_count=len(self.collected_urls),
            backoff_level=self.rate_controller.current_level,
            consecutive_success_pages=self.rate_controller.consecutive_success_count,
        )
        self.progress_persistence.save_progress(progress)
        
        # 追加新收集到的URL
        if self.collected_urls:
            self.progress_persistence.append_urls(self.collected_urls)

    
    async def _generate_crawler_script(self) -> str:
        """生成爬虫脚本"""
        detail_visits_dict = [
            {
                "detail_page_url": v.detail_page_url,
                "clicked_element_tag": v.clicked_element_tag,
                "clicked_element_text": v.clicked_element_text,
                "clicked_element_href": v.clicked_element_href,
                "clicked_element_role": v.clicked_element_role,
                "clicked_element_xpath_candidates": v.clicked_element_xpath_candidates,
            }
            for v in self.detail_visits
        ]
        
        return await self.script_generator.generate_scrapy_playwright_script(
            list_url=self.list_url,
            task_description=self.task_description,
            detail_visits=detail_visits_dict,
            nav_steps=self.nav_steps,
            collected_urls=self.collected_urls,
            common_detail_xpath=self.common_detail_xpath,
        )
    
    def _create_result(self) -> URLCollectorResult:
        """创建结果对象"""
        return URLCollectorResult(
            detail_visits=self.detail_visits,
            common_pattern=None,
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at=datetime.now().isoformat(),
        )
    
    async def _save_result(self, result: URLCollectorResult, crawler_script: str = "") -> None:
        """保存结果到文件"""
        output_file = self.output_dir / "collected_urls.json"
        
        data = {
            "list_page_url": result.list_page_url,
            "task_description": result.task_description,
            "collected_urls": result.collected_urls,
            "nav_steps": self.nav_steps,
            "detail_visits": [
                {
                    "list_page_url": v.list_page_url,
                    "detail_page_url": v.detail_page_url,
                    "clicked_element_tag": v.clicked_element_tag,
                    "clicked_element_text": v.clicked_element_text,
                    "clicked_element_href": v.clicked_element_href,
                    "clicked_element_role": v.clicked_element_role,
                    "clicked_element_xpath_candidates": v.clicked_element_xpath_candidates,
                }
                for v in result.detail_visits
            ],
            "created_at": result.created_at,
        }
        
        output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Save] 结果已保存到: {output_file}")
        
        # 保存 URL 列表
        urls_file = self.output_dir / "urls.txt"
        urls_file.write_text("\n".join(result.collected_urls), encoding="utf-8")
        print(f"[Save] URL 列表已保存到: {urls_file}")
        
        # 保存爬虫脚本
        if crawler_script:
            script_file = self.output_dir / "spider.py"
            script_file.write_text(crawler_script, encoding="utf-8")
            print(f"[Save] Scrapy 爬虫脚本已保存到: {script_file}")
            print(f"[Save] 运行方式: scrapy runspider {script_file} -o output.json")


# 便捷函数
async def collect_detail_urls(
    page: "Page",
    list_url: str,
    task_description: str,
    explore_count: int = 3,
    output_dir: str = "output",
) -> URLCollectorResult:
    """收集详情页 URL 的便捷函数"""
    collector = URLCollector(
        page=page,
        list_url=list_url,
        task_description=task_description,
        explore_count=explore_count,
        output_dir=output_dir,
    )
    return await collector.run()
