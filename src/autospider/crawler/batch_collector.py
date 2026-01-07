"""批量爬取器 - 基于配置文件执行批量 URL 收集

此模块负责流程的第二阶段：读取配置文件，执行批量 URL 收集，
支持断点续爬功能。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.config import config
from ..common.storage.redis_manager import RedisManager
from ..common.storage.persistence import CollectionConfig, ConfigPersistence, ProgressPersistence, CollectionProgress
from .checkpoint import AdaptiveRateController
from ..crawler.checkpoint.resume_strategy import ResumeCoordinator
from ..extractor.collector import (
    URLCollectorResult,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
    smart_scroll,
)
from ..common.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from ..extractor.llm import LLMDecider

if TYPE_CHECKING:
    from playwright.async_api import Page


class BatchCollector:
    """批量爬取器
    
    基于配置文件执行批量 URL 收集，支持：
    - 基于 XPath 的快速收集
    - 基于 LLM 的备用收集
    - 断点续爬
    - 速率控制
    """
    
    def __init__(
        self,
        page: "Page",
        config_path: str | Path,
        output_dir: str = "output",
    ):
        """初始化批量爬取器
        
        Args:
            page: Playwright 页面对象
            config_path: 配置文件路径
            output_dir: 输出目录
        """
        self.page = page
        self.config_path = Path(config_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 截图目录
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载配置
        self.collection_config: CollectionConfig | None = None
        self.list_url: str = ""
        self.task_description: str = ""
        self.nav_steps: list[dict] = []
        self.common_detail_xpath: str | None = None
        
        # 收集的数据
        self.collected_urls: list[str] = []
        
        # 处理器（延迟初始化）
        self.url_extractor: URLExtractor | None = None
        self.llm_decision_maker: LLMDecisionMaker | None = None
        self.navigation_handler: NavigationHandler | None = None
        self.pagination_handler: PaginationHandler | None = None
        
        # 速率控制
        self.rate_controller = AdaptiveRateController()
        
        # 持久化管理器
        self.config_persistence = ConfigPersistence(config_dir=output_dir)
        self.progress_persistence = ProgressPersistence(output_dir=output_dir)
        
        # Redis 管理器（用于持久化 URL）
        self.redis_manager: RedisManager | None = None
        if config.redis.enabled:
            import logging
            redis_logger = logging.getLogger("autospider.redis")
            if not redis_logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter("[Redis] %(message)s"))
                redis_logger.addHandler(handler)
                redis_logger.setLevel(logging.INFO)
            
            self.redis_manager = RedisManager(
                host=config.redis.host,
                port=config.redis.port,
                password=config.redis.password,
                db=config.redis.db,
                key_prefix=config.redis.key_prefix,
                logger=redis_logger,
            )
    
    async def collect_from_config(self) -> URLCollectorResult:
        """从配置文件执行批量收集（主流程）
        
        Returns:
            收集结果
        """
        print(f"\n[BatchCollector] ===== 开始批量收集 URL =====")
        
        # 0. 加载配置
        print(f"\n[Phase 0] 加载配置文件...")
        if not await self._load_config():
            print(f"[Error] 配置文件加载失败")
            return self._create_empty_result()
        
        print(f"[Phase 0] ✓ 配置加载成功")
        print(f"  - 列表页: {self.list_url}")
        print(f"  - 任务描述: {self.task_description}")
        print(f"  - 导航步骤: {len(self.nav_steps)} 个")
        print(f"  - 公共 XPath: {'已配置' if self.common_detail_xpath else '未配置'}")
        
        # 0.5 连接 Redis 并加载历史 URL（断点续爬）
        if self.redis_manager:
            await self.redis_manager.connect()
            urls = await self.redis_manager.load_items()
            if urls:
                self.collected_urls.extend(urls)
                print(f"[Redis] 已加载 {len(urls)} 个历史 URL")
        
        # 0.6 加载历史进度
        previous_progress = self.progress_persistence.load_progress()
        target_page_num = 1
        is_resume = False
        
        if previous_progress and previous_progress.current_page_num > 1:
            print(f"\n[断点恢复] 检测到上次中断在第 {previous_progress.current_page_num} 页")
            print(f"[断点恢复] 已收集 {previous_progress.collected_count} 个 URL")
            target_page_num = previous_progress.current_page_num
            is_resume = True
            
            # 恢复速率控制器状态
            self.rate_controller.current_level = previous_progress.backoff_level
            self.rate_controller.consecutive_success_count = previous_progress.consecutive_success_pages
            print(f"[断点恢复] 恢复速率控制状态: 等级={previous_progress.backoff_level}, 连续成功={previous_progress.consecutive_success_pages}")
        
        # 1. 导航到列表页
        print(f"\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 初始化处理器
        self._initialize_handlers()
        
        # 2. 重放导航步骤（如果有）
        if self.nav_steps:
            print(f"\n[Phase 2] 重放导航步骤...")
            nav_success = await self.navigation_handler.replay_nav_steps(self.nav_steps)
            if not nav_success:
                print(f"[Warning] 导航步骤重放失败")
        
        # 3. 断点恢复：跳转到目标页
        if target_page_num > 1:
            print(f"\n[Phase 3] 断点恢复：尝试跳转到第 {target_page_num} 页...")
            actual_page = await self._resume_to_target_page(target_page_num)
            self.pagination_handler.current_page_num = actual_page
            print(f"[Phase 3] ✓ 已定位到第 {actual_page} 页，继续收集")
        
        # 4. 收集阶段
        if self.common_detail_xpath:
            print(f"\n[Phase 4] 收集阶段：使用公共 xpath 遍历列表页...")
            await self._collect_phase_with_xpath()
        else:
            print(f"\n[Phase 4] 收集阶段：LLM 遍历列表页...")
            await self._collect_phase_with_llm()
        
        # 5. 保存结果
        result = self._create_result()
        print(f"\n[Complete] 收集完成!")
        print(f"  - 收集到 {len(self.collected_urls)} 个详情页 URL")
        
        await self._save_result(result)
        
        return result
    
    async def _load_config(self) -> bool:
        """加载配置文件
        
        Returns:
            是否加载成功
        """
        if not self.config_path.exists():
            print(f"[Error] 配置文件不存在: {self.config_path}")
            return False
        
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.collection_config = CollectionConfig.from_dict(data)
            
            # 提取配置信息
            self.list_url = self.collection_config.list_url
            self.task_description = self.collection_config.task_description
            self.nav_steps = self.collection_config.nav_steps
            self.common_detail_xpath = self.collection_config.common_detail_xpath
            
            return True
        except Exception as e:
            print(f"[Error] 加载配置失败: {e}")
            return False
    
    def _initialize_handlers(self):
        """初始化各个处理器"""
        self.url_extractor = URLExtractor(self.page, self.list_url)
        
        # LLM 决策器（仅在需要时初始化）
        if not self.common_detail_xpath:
            decider = LLMDecider()
            self.llm_decision_maker = LLMDecisionMaker(
                page=self.page,
                decider=decider,
                task_description=self.task_description,
                collected_urls=self.collected_urls,
                visited_detail_urls=set(),
                list_url=self.list_url,
            )
        
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=10,
            decider=LLMDecider() if not self.common_detail_xpath else None,
            screenshots_dir=self.screenshots_dir,
        )
        
        self.pagination_handler = PaginationHandler(
            page=self.page,
            list_url=self.list_url,
            screenshots_dir=self.screenshots_dir,
            llm_decision_maker=self.llm_decision_maker,
        )
        
        # 加载分页配置
        if self.collection_config:
            if self.collection_config.pagination_xpath:
                self.pagination_handler.pagination_xpath = self.collection_config.pagination_xpath
            if self.collection_config.jump_widget_xpath:
                self.pagination_handler.jump_widget_xpath = self.collection_config.jump_widget_xpath
    
    async def _resume_to_target_page(self, target_page_num: int) -> int:
        """使用三阶段策略恢复到目标页
        
        Args:
            target_page_num: 目标页码
            
        Returns:
            实际到达的页码
        """
        coordinator = ResumeCoordinator(
            list_url=self.list_url,
            collected_urls=set(self.collected_urls),
            jump_widget_xpath=self.collection_config.jump_widget_xpath if self.collection_config else None,
            detail_xpath=self.common_detail_xpath,
            pagination_xpath=self.collection_config.pagination_xpath if self.collection_config else None,
        )
        
        actual_page = await coordinator.resume_to_page(self.page, target_page_num)
        return actual_page
    
    async def _collect_phase_with_xpath(self) -> None:
        """收集阶段：使用公共 xpath 直接提取 URL"""
        if not self.common_detail_xpath:
            return
        
        # 返回列表页开始位置
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
                    except:
                        pass
                    
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
    
    def _create_result(self) -> URLCollectorResult:
        return URLCollectorResult(
            detail_visits=[],
            common_pattern=None,
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at=datetime.now().isoformat(),
        )
    
    def _create_empty_result(self) -> URLCollectorResult:
        return URLCollectorResult(
            detail_visits=[],
            common_pattern=None,
            collected_urls=[],
            list_page_url="",
            task_description="",
            created_at=datetime.now().isoformat(),
        )
    
    async def _save_result(self, result: URLCollectorResult) -> None:
        """保存结果到文件"""
        output_file = self.output_dir / "collected_urls.json"
        
        data = {
            "list_page_url": result.list_page_url,
            "task_description": result.task_description,
            "collected_urls": result.collected_urls,
            "created_at": result.created_at,
        }
        
        output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Save] 结果已保存到: {output_file}")
        
        # 保存 URL 列表
        urls_file = self.output_dir / "urls.txt"
        urls_file.write_text("\n".join(result.collected_urls), encoding="utf-8")
        print(f"[Save] URL 列表已保存到: {urls_file}")


# 便捷函数
async def batch_collect_urls(
    page: "Page",
    config_path: str | Path,
    output_dir: str = "output",
) -> URLCollectorResult:
    """批量收集 URL 的便捷函数
    
    Args:
        page: Playwright 页面对象
        config_path: 配置文件路径
        output_dir: 输出目录
        
    Returns:
        收集结果
    """
    collector = BatchCollector(
        page=page,
        config_path=config_path,
        output_dir=output_dir,
    )
    return await collector.collect_from_config()
