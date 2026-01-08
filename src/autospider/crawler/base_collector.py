"""BaseCollector 基类

抽取 URLCollector 和 BatchCollector 的公共逻辑，
减少代码重复，提高可维护性。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from ..common.config import config
from ..common.logger import get_logger
from ..common.exceptions import PageLoadError, CollectionError
from ..common.storage.persistence import CollectionProgress, ProgressPersistence
from .checkpoint import AdaptiveRateController
from .checkpoint.resume_strategy import ResumeCoordinator
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

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..common.storage.redis_manager import RedisManager

# 日志器
logger = get_logger(__name__)


class BaseCollector(ABC):
    """URL 收集器基类
    
    提供公共的收集逻辑：
    - 速率控制
    - 断点续爬
    - Redis 持久化
    - XPath/LLM 收集
    - 分页处理
    """
    
    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        output_dir: str = "output",
    ):
        """初始化基类
        
        Args:
            page: Playwright 页面对象
            list_url: 列表页 URL
            task_description: 任务描述
            output_dir: 输出目录
        """
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        
        # 输出目录
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 收集的数据
        self.collected_urls: list[str] = []
        self.nav_steps: list[dict] = []
        self.common_detail_xpath: str | None = None
        
        # 速率控制
        self.rate_controller = AdaptiveRateController()
        logger.info(f"速率控制器已初始化 (基础延迟: {self.rate_controller.base_delay}s)")
        
        # 持久化管理器
        self.progress_persistence = ProgressPersistence(output_dir=output_dir)
        
        # 处理器（延迟初始化）
        self.url_extractor: URLExtractor | None = None
        self.llm_decision_maker: LLMDecisionMaker | None = None
        self.navigation_handler: NavigationHandler | None = None
        self.pagination_handler: PaginationHandler | None = None
        
        # Redis 管理器
        self.redis_manager: "RedisManager | None" = None
        self._init_redis_manager()
    
    def _init_redis_manager(self) -> None:
        """初始化 Redis 管理器"""
        if not config.redis.enabled:
            return
        
        try:
            from ..common.storage.redis_manager import RedisManager
            
            self.redis_manager = RedisManager(
                host=config.redis.host,
                port=config.redis.port,
                password=config.redis.password,
                db=config.redis.db,
                key_prefix=config.redis.key_prefix,
                logger=logger,
            )
        except ImportError:
            logger.warning("Redis 依赖未安装，使用 pip install autospider[redis] 安装")
    
    def _initialize_handlers(self) -> None:
        """初始化各个处理器
        
        子类可覆盖此方法添加额外的初始化逻辑。
        """
        self.url_extractor = URLExtractor(self.page, self.list_url)
        
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=10,
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
        if self.pagination_handler:
            self.pagination_handler.page = page
            if list_url:
                self.pagination_handler.list_url = list_url
        if self.llm_decision_maker:
            self.llm_decision_maker.page = page
            if list_url:
                self.llm_decision_maker.list_url = list_url
        if self.navigation_handler:
            self.navigation_handler.page = page
            if list_url:
                self.navigation_handler.list_url = list_url

    def _is_progress_compatible(self, progress: CollectionProgress | None) -> bool:
        """检查进度是否与当前任务匹配"""
        if not progress:
            return False
        if progress.list_url and progress.list_url != self.list_url:
            return False
        if progress.task_description and progress.task_description != self.task_description:
            return False
        return True

    async def _load_previous_urls(self) -> None:
        """从 Redis 或本地文件加载历史 URL（用于断点续爬）"""
        loaded_urls: list[str] = []

        if self.redis_manager:
            client = await self.redis_manager.connect()
            if client:
                urls = await self.redis_manager.load_items()
                if urls:
                    loaded_urls.extend(urls)
                    logger.info(f"从 Redis 加载了 {len(urls)} 个历史 URL")

        file_urls = self.progress_persistence.load_collected_urls()
        if file_urls:
            loaded_urls.extend(file_urls)
            logger.info(f"从本地文件加载了 {len(file_urls)} 个历史 URL")

        if not loaded_urls:
            return

        existing = set(self.collected_urls)
        new_urls = [url for url in loaded_urls if url and url not in existing]
        if new_urls:
            self.collected_urls.extend(new_urls)
            logger.info(f"合并后历史 URL 总数: {len(self.collected_urls)}")
    
    async def _resume_to_target_page(
        self,
        target_page_num: int,
        jump_widget_xpath: dict[str, str] | None = None,
        pagination_xpath: str | None = None,
    ) -> int:
        """使用三阶段策略恢复到目标页
        
        Args:
            target_page_num: 目标页码
            jump_widget_xpath: 跳转控件 XPath
            pagination_xpath: 分页控件 XPath
            
        Returns:
            实际到达的页码
        """
        coordinator = ResumeCoordinator(
            list_url=self.list_url,
            collected_urls=set(self.collected_urls),
            jump_widget_xpath=jump_widget_xpath,
            detail_xpath=self.common_detail_xpath,
            pagination_xpath=pagination_xpath,
        )
        
        actual_page = await coordinator.resume_to_page(self.page, target_page_num)
        return actual_page
    
    async def _collect_phase_with_xpath(self) -> None:
        """收集阶段：使用公共 XPath 直接提取 URL"""
        if not self.common_detail_xpath:
            return
        
        logger.info("返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 重放导航步骤
        if self.nav_steps and self.navigation_handler:
            await self.navigation_handler.replay_nav_steps(self.nav_steps)
        
        max_pages = config.url_collector.max_pages
        target_url_count = config.url_collector.target_url_count
        
        logger.info(f"目标：收集 {target_url_count} 个 URL，最大翻页: {max_pages}")
        
        # 翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            logger.info(f"===== 第 {self.pagination_handler.current_page_num} 页 =====")
            
            if len(self.collected_urls) >= target_url_count:
                logger.info(f"✓ 已达到目标数量 {target_url_count}")
                break
            
            # 应用速率控制延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                logger.debug(f"等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)
            
            # 使用 XPath 提取 URL
            page_success = await self._extract_urls_with_xpath()
            
            # 记录结果
            if page_success:
                self.rate_controller.record_success()
            
            # 保存进度
            self._save_progress()
            
            # 翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                logger.info("无法翻页，结束收集")
                break
        
        logger.info(f"收集完成! 共收集 {len(self.collected_urls)} 个 URL")
    
    async def _extract_urls_with_xpath(self) -> bool:
        """使用 XPath 提取当前页的 URL
        
        Returns:
            是否成功提取到新 URL
        """
        urls_before = len(self.collected_urls)
        target_url_count = config.url_collector.target_url_count
        
        try:
            locators = self.page.locator(f"xpath={self.common_detail_xpath}")
            count = await locators.count()
            logger.info(f"找到 {count} 个匹配元素")
            
            for i in range(count):
                if len(self.collected_urls) >= target_url_count:
                    break
                
                locator = locators.nth(i)
                
                # 尝试从 href 获取
                try:
                    href = await locator.get_attribute("href")
                    if href:
                        url = urljoin(self.list_url, href)
                        if url not in self.collected_urls:
                            self.collected_urls.append(url)
                            if self.redis_manager:
                                await self.redis_manager.save_item(url)
                            logger.info(f"✓ [{i+1}/{count}] {url[:60]}...")
                        continue
                except Exception as e:
                    logger.debug(f"获取 href 失败: {e}")
                
                # 点击获取
                if self.url_extractor:
                    url = await self.url_extractor.click_element_and_get_url(
                        locator, self.nav_steps
                    )
                    if url and url not in self.collected_urls:
                        self.collected_urls.append(url)
                        if self.redis_manager:
                            await self.redis_manager.save_item(url)
                        logger.info(f"✓ [{i+1}/{count}] {url[:60]}...")
            
            return len(self.collected_urls) > urls_before
            
        except Exception as e:
            logger.error(f"XPath 提取失败: {e}")
            self.rate_controller.apply_penalty()
            return False
    
    async def _collect_phase_with_llm(self) -> None:
        """收集阶段：使用 LLM 遍历列表页"""
        logger.info("返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        target_url_count = config.url_collector.target_url_count
        max_pages = config.url_collector.max_pages
        
        logger.info(f"目标：收集 {target_url_count} 个 URL，最大翻页: {max_pages}")
        
        # 翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            logger.info(f"===== 第 {self.pagination_handler.current_page_num} 页 =====")
            
            if len(self.collected_urls) >= target_url_count:
                logger.info("✓ 已达到目标数量")
                break
            
            # 应用速率控制延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                logger.debug(f"等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)
            
            # 滚动收集
            page_success = await self._collect_page_with_llm(max_scrolls, no_new_threshold)
            
            # 记录结果
            if page_success:
                self.rate_controller.record_success()
            
            # 保存进度
            self._save_progress()
            
            # 翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                logger.info("无法翻页，结束收集")
                break
        
        logger.info(f"收集完成! 共收集 {len(self.collected_urls)} 个 URL")
    
    async def _collect_page_with_llm(
        self, max_scrolls: int, no_new_threshold: int
    ) -> bool:
        """使用 LLM 收集单页的 URL
        
        Args:
            max_scrolls: 最大滚动次数
            no_new_threshold: 连续无新 URL 的阈值
            
        Returns:
            是否成功收集到新 URL
        """
        if not self.llm_decision_maker:
            logger.warning("LLM 决策器未初始化")
            return False
        
        target_url_count = config.url_collector.target_url_count
        scroll_count = 0
        last_url_count = len(self.collected_urls)
        no_new_urls_count = 0
        page_success = False
        
        try:
            while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
                if len(self.collected_urls) >= target_url_count:
                    break
                
                logger.debug(f"滚动 {scroll_count + 1}/{max_scrolls}")
                
                # 扫描页面
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                
                # LLM 识别
                llm_decision = await self.llm_decision_maker.ask_for_decision(
                    snapshot, screenshot_base64
                )
                
                if llm_decision and llm_decision.get("action") == "select_detail_links":
                    mark_id_text_map = llm_decision.get("mark_id_text_map", {})
                    old_mark_ids = llm_decision.get("mark_ids", [])
                    mark_ids: list[int] = []
                    
                    if mark_id_text_map:
                        if config.url_collector.validate_mark_id:
                            from ..extractor.validator.mark_id_validator import MarkIdValidator
                            
                            validator = MarkIdValidator()
                            mark_ids, _ = validator.validate_mark_id_text_map(
                                mark_id_text_map, snapshot
                            )
                        else:
                            mark_ids = [int(k) for k in mark_id_text_map.keys()]
                    elif old_mark_ids:
                        mark_ids = old_mark_ids
                    
                    logger.info(f"LLM 识别到 {len(mark_ids)} 个详情链接")
                    
                    candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                    
                    for candidate in candidates:
                        if self.url_extractor:
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
                    logger.debug(f"连续 {no_new_urls_count} 次无新 URL")
                else:
                    no_new_urls_count = 0
                    logger.info(f"✓ 当前已收集 {current_count} 个 URL")
                    last_url_count = current_count
                    page_success = True
                
                # 滚动
                if not await smart_scroll(self.page):
                    logger.info("已到达页面底部")
                    break
                scroll_count += 1
            
        except Exception as e:
            logger.error(f"LLM 收集过程出错: {e}")
            self.rate_controller.apply_penalty()
        
        return page_success
    
    def _save_progress(self) -> None:
        """保存收集进度"""
        progress = CollectionProgress(
            status="RUNNING",
            list_url=self.list_url,
            task_description=self.task_description,
            current_page_num=(
                self.pagination_handler.current_page_num 
                if self.pagination_handler else 1
            ),
            collected_count=len(self.collected_urls),
            backoff_level=self.rate_controller.current_level,
            consecutive_success_pages=self.rate_controller.consecutive_success_count,
        )
        self.progress_persistence.save_progress(progress)
    
    def _create_result(self) -> URLCollectorResult:
        """创建收集结果"""
        return URLCollectorResult(
            detail_visits=[],
            common_pattern=None,
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at=datetime.now().isoformat(),
        )
    
    @abstractmethod
    async def run(self) -> URLCollectorResult:
        """运行收集流程（子类实现）"""
        pass
