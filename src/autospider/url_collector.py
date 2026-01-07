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

from .config import config
from .redis_manager import RedisManager
from .llm import LLMDecider
from .llm.prompt_template import render_template
from .persistence import CollectionConfig, ConfigPersistence, ProgressPersistence, CollectionProgress
from .script_generator import ScriptGenerator
from .checkpoint import AdaptiveRateController
from .som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    format_marks_for_llm,
    inject_and_scan,
)
from .mark_id_validator import MarkIdValidator
from .collector import (
    DetailPageVisit,
    URLCollectorResult,
    XPathExtractor,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
    smart_scroll,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .types import SoMSnapshot


# Prompt 模板文件路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent.parent / "prompts" / "url_collector.yaml")


class URLCollector:
    """详情页 URL 收集器（协调器）"""
    
    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        explore_count: int = 3,
        max_nav_steps: int = 10,
        output_dir: str = "output",
    ):
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.explore_count = explore_count
        self.max_nav_steps = max_nav_steps
        
        # 输出目录
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态
        self.detail_visits: list[DetailPageVisit] = []
        self.collected_urls: list[str] = []
        self.step_index = 0
        self.nav_steps: list[dict] = []
        self.common_detail_xpath: str | None = None
        self.visited_detail_urls: set[str] = set()
        
        # 初始化各个组件
        self.decider = LLMDecider()
        self.script_generator = ScriptGenerator(output_dir)
        self.config_persistence = ConfigPersistence(output_dir)
        self.progress_persistence = ProgressPersistence(output_dir)
        
        # 自适应速率控制器
        self.rate_controller = AdaptiveRateController()
        print(f"[速率控制] 已初始化速率控制器")
        print(f"[速率控制] 基础延迟: {self.rate_controller.base_delay}秒, 退避因子: {self.rate_controller.backoff_factor}")
        
        # 初始化处理器
        self.xpath_extractor = XPathExtractor()
        self.llm_decision_maker: LLMDecisionMaker | None = None  # 延迟初始化
        self.url_extractor = URLExtractor(page, list_url)
        self.navigation_handler: NavigationHandler | None = None  # 延迟初始化
        self.pagination_handler: PaginationHandler | None = None  # 延迟初始化
        
        # LLM（用于决策）
        self.llm = ChatOpenAI(
            api_key=config.llm.planner_api_key or config.llm.api_key,
            base_url=config.llm.planner_api_base or config.llm.api_base,
            model=config.llm.planner_model or config.llm.model,
            temperature=0.1,
            max_tokens=4096,
        )
        
        # Redis 管理器（用于持久化 URL）
        self.redis_manager: RedisManager | None = None
        if config.redis.enabled:
            self.redis_manager = RedisManager(
                host=config.redis.host,
                port=config.redis.port,
                password=config.redis.password,
                db=config.redis.db,
                key_prefix=config.redis.key_prefix,
            )
    
    async def run(self) -> URLCollectorResult:
        """运行 URL 收集流程"""
        print(f"\n[URLCollector] ===== 开始收集详情页 URL =====")
        print(f"[URLCollector] 任务描述: {self.task_description}")
        print(f"[URLCollector] 列表页: {self.list_url}")
        print(f"[URLCollector] 将探索 {self.explore_count} 个详情页")
        
        # 0. 连接 Redis 并加载历史 URL（断点续爬）
        if self.redis_manager:
            await self.redis_manager.connect()
            urls = await self.redis_manager.load_urls()
            if urls:
                self.collected_urls.extend(urls)
                self.visited_detail_urls.update(urls)
        
        # 1. 导航到列表页
        print(f"\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 初始化延迟组件
        self._initialize_handlers()
        
        # 2. 导航阶段
        print(f"\n[Phase 2] 导航阶段：根据任务描述进行筛选操作...")
        nav_success = await self.navigation_handler.run_navigation_phase()
        if not nav_success:
            print(f"[Warning] 导航阶段未能完成筛选，将直接在当前页面探索")
        
        # 保存导航步骤
        self.nav_steps = self.navigation_handler.nav_steps
        
        # 3. 探索阶段
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
        print(f"\n[Phase 3.6] 提取分页控件 xpath...")
        pagination_xpath = await self.pagination_handler.extract_pagination_xpath()
        if pagination_xpath:
            print(f"[Phase 3.6] ✓ 提取到分页控件 xpath: {pagination_xpath}")
        else:
            print(f"[Phase 3.6] ⚠ 未找到分页控件，将只收集当前页")
        
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
    
    def _initialize_handlers(self):
        """初始化各个处理器"""
        self.llm_decision_maker = LLMDecisionMaker(
            page=self.page,
            decider=self.decider,
            task_description=self.task_description,
            collected_urls=self.collected_urls,
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
            # 这里可以实现重试逻辑，为简化暂时跳过
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
                                    await self.redis_manager.save_url(url)
                                print(f"[Collect-XPath] ✓ [{i+1}/{count}] {url[:60]}...")
                            continue
                    except:
                        pass
                    
                    # 点击获取
                    url = await self.url_extractor.click_element_and_get_url(locator, self.nav_steps)
                    if url and url not in self.collected_urls:
                        self.collected_urls.append(url)
                        if self.redis_manager:
                            await self.redis_manager.save_url(url)
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
                        mark_ids = llm_decision.get("mark_ids", [])
                        print(f"[Collect] LLM 识别到 {len(mark_ids)} 个详情链接")
                        
                        candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                        
                        for candidate in candidates:
                            url = await self.url_extractor.extract_from_element(candidate, snapshot)
                            if url and url not in self.collected_urls:
                                self.collected_urls.append(url)
                                if self.redis_manager:
                                    await self.redis_manager.save_url(url)
                    
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
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)
        print(f"[Phase 4.5] ✓ 配置已持久化")
    
    def _save_progress(self):
        """保存收集进度"""
        progress = CollectionProgress(
            status="RUNNING",
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
