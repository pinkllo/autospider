"""BaseCollector 基类

抽取 URLCollector 和 BatchCollector 的公共逻辑，
减少代码重复，提高可维护性。

下一轮拆分入口已经固定：
- ProgressStore：进度持久化 / 历史 URL 恢复
- UrlPublishService：URL 去重后发布到 queue backend
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from ..checkpoint import AdaptiveRateController
from ..checkpoint.resume_strategy import ResumeCoordinator
from ..collector import (
    URLCollectorResult,
    LLMDecisionMaker,
    URLExtractor,
    NavigationHandler,
    PaginationHandler,
    smart_scroll,
)
from autospider.platform.browser.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from autospider.platform.browser.som.text_first import resolve_mark_ids_from_map
from .progress_store import ProgressStore
from .url_publish_service import UrlPublishService

if TYPE_CHECKING:
    from playwright.async_api import Page
    from autospider.contexts.collection.infrastructure.channel.base import URLChannel

# 日志器
logger = get_logger(__name__)


class BaseCollector(ABC):
    """URL 收集器基类

    提供公共的收集逻辑：
    - 速率控制
    - 断点续爬
    - queue / 进度恢复边界
    - XPath/LLM 收集
    - 分页处理

    注意：不要继续向这个基类新增 queue/progress/persistence 逻辑，
    这些职责将在下一轮拆到 ProgressStore / UrlPublishService。
    """

    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        execution_brief: dict | None = None,
        output_dir: str = "output",
        url_channel: "URLChannel | None" = None,
        target_url_count: int | None = None,
        max_pages: int | None = None,
        persist_progress: bool = True,
    ):
        """初始化 BaseCollector 基类

        Args:
            page: Playwright 页面实例，用于浏览器交互
            list_url: 目标列表页的起始 URL
            task_description: 对当前采集任务的自然语言描述（用于 LLM 理解）
            output_dir: 结果文件和截图的存储根目录
            target_url_count: 目标采集 URL 数量（可覆盖配置）
        """
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.execution_brief = dict(execution_brief or {})
        self.persist_progress = bool(persist_progress)

        # 初始化输出路径
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 运行时数据存储
        self.collected_urls: list[str] = []
        # 存储探索阶段产生的导航步骤（点击、输入等），用于在后续页面重放
        self.nav_steps: list[dict] = []
        # 存储自动发现的详情页 XPath，若存在则优先使用 XPath 模式提高效率
        self.common_detail_xpath: str | None = None

        # 目标采集数量（可由调用方覆盖配置）
        self.target_url_count = (
            int(target_url_count)
            if target_url_count is not None
            else config.url_collector.target_url_count
        )
        self.max_pages = int(max_pages) if max_pages is not None else config.url_collector.max_pages

        # 自适应速率控制器：根据页面加载成功率动态调整抓取频率，降低封号风险
        self.rate_controller = AdaptiveRateController()
        logger.info(f"速率控制器已初始化 (基础延迟: {self.rate_controller.base_delay}s)")

        # 各核心功能处理器（采用延迟加载/初始化策略）
        self.url_extractor: URLExtractor | None = None  # URL 提取逻辑
        self.llm_decision_maker: LLMDecisionMaker | None = None  # LLM 决策逻辑
        self.navigation_handler: NavigationHandler | None = None  # 页面导航/重放逻辑
        self.pagination_handler: PaginationHandler | None = None  # 分页处理逻辑

        self.progress_store = ProgressStore(output_dir=output_dir)
        self.url_publish_service = UrlPublishService(
            output_dir=output_dir,
            url_channel=url_channel,
        )

    def _initialize_handlers(self) -> None:
        """初始化所有子处理器组件

        此方法通常在子类的 run 方法开始时调用，以确保所有依赖组件都已就绪。
        """
        # 初始化 URL 提取器
        self.url_extractor = URLExtractor(self.page, self.list_url)

        # 初始化导航处理器，负责记录和重放用户操作
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=10,
            execution_brief=self.execution_brief,
            screenshots_dir=self.screenshots_dir,
        )

        # 初始化分页处理器，负责识别和点击“下一页”
        self.pagination_handler = PaginationHandler(
            page=self.page,
            list_url=self.list_url,
            screenshots_dir=self.screenshots_dir,
            llm_decision_maker=self.llm_decision_maker,
        )

    def _sync_page_references(self, page: "Page", list_url: str | None = None) -> None:
        """更新所有子处理器中的页面对象引用

        在浏览器重启或页面上下文切换后，需要调用此方法确保所有组件操作的是同一个 Page 实例。

        Args:
            page: 新的 Playwright 页面对象
            list_url: 可选的新起始 URL
        """
        self.page = page
        if list_url:
            self.list_url = list_url

        # 同步更新各处理器的引用
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

    async def restore_collected_urls(self) -> None:
        """加载已采集的历史 URL 数据。"""
        loaded_urls = await self.url_publish_service.load_existing_urls()
        if not loaded_urls:
            return
        existing = set(self.collected_urls)
        new_urls = [url for url in loaded_urls if url not in existing]
        if new_urls:
            self.collected_urls.extend(new_urls)
            logger.info(f"合并后历史 URL 总数: {len(self.collected_urls)}")

    async def remember_collected_url(self, url: str) -> bool:
        """记录并发布一个新 URL。"""
        normalized = str(url or "").strip()
        if not normalized or normalized in self.collected_urls:
            return False
        self.collected_urls.append(normalized)
        await self.url_publish_service.publish(normalized)
        return True

    def save_running_progress(self) -> None:
        self.save_progress_status(status="RUNNING")

    def save_progress_status(
        self,
        *,
        status: str,
        pause_reason: str | None = None,
    ) -> None:
        if not self.persist_progress:
            return
        current_page_num = (
            self.pagination_handler.current_page_num if self.pagination_handler else 1
        )
        self.progress_store.save(
            status=status,
            pause_reason=pause_reason,
            list_url=self.list_url,
            task_description=self.task_description,
            current_page_num=current_page_num,
            collected_count=len(self.collected_urls),
            backoff_level=self.rate_controller.current_level,
            consecutive_success_pages=self.rate_controller.consecutive_success_count,
        )

    async def _resume_to_target_page(
        self,
        target_page_num: int,
        jump_widget_xpath: dict[str, str] | None = None,
        pagination_xpath: str | None = None,
    ) -> int:
        """执行断点恢复：通过三阶段策略快速定位到目标页码

        策略包含：直接跳转、翻页搜索、以及通过详情页内容验证当前页位置。

        Args:
            target_page_num: 目标恢复到的页码
            jump_widget_xpath: 跳转输入框和按钮的 XPath（若存在可加速定位）
            pagination_xpath: 分页链接的 XPath

        Returns:
            int: 实际成功到达的页码
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
        """基于 XPath 模板的高效采集阶段

        当已经获取到详情页的 XPath 模式时，优先使用此方法进行批量提取和翻页。
        """
        if not self.common_detail_xpath:
            return

        # 断点续爬处理：如果已经在目标页，则不要重置回第一页
        if self.pagination_handler and self.pagination_handler.current_page_num > 1:
            logger.info(
                f"断点恢复：从当前页面继续收集（第 {self.pagination_handler.current_page_num} 页）"
            )
        else:
            logger.info("返回列表页开始位置...")
            await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

        max_pages = self.max_pages
        target_url_count = self.target_url_count

        logger.info(f"目标：收集 {target_url_count} 个 URL，最大翻页: {max_pages}")

        # 核心翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            logger.info(f"===== 第 {self.pagination_handler.current_page_num} 页 =====")

            # 检查是否达到目标数量
            if len(self.collected_urls) >= target_url_count:
                logger.info(f"✓ 已达到目标数量 {target_url_count}")
                break

            # 速率控制：翻页前进行自适应延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                logger.debug(f"等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)

            # 提取当前页 URL
            page_success = await self._extract_urls_with_xpath()

            # 记录成功状态以调整后续延迟
            if page_success:
                self.rate_controller.record_success()

            # 实时保存进度
            self.save_running_progress()

            if len(self.collected_urls) >= target_url_count:
                break

            # 点击下一页
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                logger.info("无法翻页，结束收集")
                break

        logger.info(f"收集完成! 共收集 {len(self.collected_urls)} 个 URL")

    async def _extract_urls_with_xpath(self) -> bool:
        """在当前页面使用 XPath 模板提取详情页 URL

        支持两种模式：
        1. 直接从元素的 href 属性获取 URL（最快）
        2. 若 href 为空，则模拟点击元素并获取跳转后的 URL

        Returns:
            bool: 本次提取是否发现了新的、未采集过的 URL
        """
        urls_before = len(self.collected_urls)
        target_url_count = self.target_url_count

        try:
            # 获取所有匹配 XPath 的元素
            locators = self.page.locator(f"xpath={self.common_detail_xpath}")
            count = await locators.count()
            logger.info(f"找到 {count} 个匹配元素")

            for i in range(count):
                if len(self.collected_urls) >= target_url_count:
                    break

                locator = locators.nth(i)
                if self.url_extractor:
                    url = await self.url_extractor.extract_from_locator(locator, self.nav_steps)
                    if url and url not in self.collected_urls:
                        if await self.remember_collected_url(url):
                            logger.info(f"✓ [{i+1}/{count}] {url[:60]}...")

            return len(self.collected_urls) > urls_before

        except Exception as e:
            logger.error(f"XPath 提取失败: {e}")
            self.rate_controller.apply_penalty()  # 出错时增加惩罚延迟
            return False

    async def _collect_phase_with_llm(self) -> None:
        """基于 LLM 视觉识别的智能采集阶段

        在没有稳定 XPath 模板或页面结构复杂时使用，通过 LLM 识别页面上的详情链接。
        """
        # 断点续爬处理
        if self.pagination_handler and self.pagination_handler.current_page_num > 1:
            logger.info(
                f"断点恢复：从当前页面继续收集（第 {self.pagination_handler.current_page_num} 页）"
            )
        else:
            logger.info("返回列表页开始位置...")
            await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            # 重放探索阶段记录的导航步骤（如：点击菜单、选择分类等）
            if self.nav_steps and self.navigation_handler:
                await self.navigation_handler.replay_nav_steps(self.nav_steps)

        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        target_url_count = self.target_url_count
        max_pages = self.max_pages

        logger.info(f"目标：收集 {target_url_count} 个 URL，最大翻页: {max_pages}")

        # 核心翻页循环
        while self.pagination_handler.current_page_num <= max_pages:
            logger.info(f"===== 第 {self.pagination_handler.current_page_num} 页 =====")

            if len(self.collected_urls) >= target_url_count:
                logger.info("✓ 已达到目标数量")
                break

            # 自适应延迟
            delay = self.rate_controller.get_delay()
            if config.url_collector.debug_delay:
                logger.debug(f"等待 {delay:.2f}秒 (等级: {self.rate_controller.current_level})")
            await asyncio.sleep(delay)

            # 执行单页内的智能滚动和识别收集
            page_success = await self._collect_page_with_llm(max_scrolls, no_new_threshold)

            if page_success:
                self.rate_controller.record_success()

            self.save_running_progress()

            if len(self.collected_urls) >= target_url_count:
                break

            # 翻页
            page_turned = await self.pagination_handler.find_and_click_next_page()
            if not page_turned:
                logger.info("无法翻页，结束收集")
                break

        logger.info(f"收集完成! 共收集 {len(self.collected_urls)} 个 URL")

    async def _collect_page_with_llm(self, max_scrolls: int, no_new_threshold: int) -> bool:
        """在单页内使用 LLM 识别和滚动采集 URL

        采用 SoM (Set of Mark) 技术：先对页面元素打标，再让 LLM 根据视觉快照选择链接。

        Args:
            max_scrolls: 单页最大向下滚动次数（支持瀑布流）
            no_new_threshold: 连续多少次滚动没有新 URL 则停止滚动

        Returns:
            bool: 本页是否成功收集到了新 URL
        """
        if not self.llm_decision_maker:
            logger.warning("LLM 决策器未初始化")
            return False

        target_url_count = self.target_url_count
        scroll_count = 0
        last_url_count = len(self.collected_urls)
        no_new_urls_count = 0
        page_success = False

        try:
            while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
                if len(self.collected_urls) >= target_url_count:
                    break

                logger.debug(f"滚动 {scroll_count + 1}/{max_scrolls}")

                # 1. 扫描页面并生成 SoM 快照
                await clear_overlay(self.page)  # 清除之前的打标层
                snapshot = await inject_and_scan(self.page)  # 注入脚本并扫描交互元素
                _, screenshot_base64 = await capture_screenshot_with_marks(
                    self.page
                )  # 获取带标记的截图

                # 2. 请求 LLM 进行决策
                llm_decision = await self.llm_decision_maker.ask_for_decision(
                    snapshot, screenshot_base64
                )

                if llm_decision and llm_decision.get("action") == "select":
                    args = (
                        llm_decision.get("args")
                        if isinstance(llm_decision.get("args"), dict)
                        else {}
                    )
                    purpose = (args.get("purpose") or "").lower()
                    if purpose in {"detail_links", "detail_link", "detail"}:
                        items = args.get("items") or []
                        mark_id_text_map: dict[str, str] = {}
                        for idx, it in enumerate(items):
                            if not isinstance(it, dict):
                                continue
                            text_value = str(it.get("text") or it.get("target_text") or "").strip()
                            if not text_value:
                                continue
                            raw_mark_id = it.get("mark_id")
                            key = (
                                str(raw_mark_id) if raw_mark_id is not None else f"text_only_{idx}"
                            )
                            mark_id_text_map[key] = text_value
                        if not mark_id_text_map:
                            mark_id_text_map = args.get("mark_id_text_map", {}) or {}

                        mark_ids: list[int] = []
                        if mark_id_text_map:
                            # 文本优先：当启用验证，或存在 text-only 项时，都按文本解析。
                            should_resolve_by_text = config.url_collector.validate_mark_id or any(
                                not str(k).isdigit() for k in mark_id_text_map.keys()
                            )
                            if should_resolve_by_text:
                                try:
                                    mark_ids = await resolve_mark_ids_from_map(
                                        page=self.page,
                                        llm=self.llm_decision_maker.decider.llm,
                                        snapshot=snapshot,
                                        mark_id_text_map=mark_id_text_map,
                                        max_retries=config.url_collector.max_validation_retries,
                                    )
                                except Exception as e:
                                    logger.warning(f"文本解析 mark_id 失败，回退数字 id: {e}")
                                    mark_ids = [
                                        int(k) for k in mark_id_text_map.keys() if str(k).isdigit()
                                    ]
                            else:
                                mark_ids = [
                                    int(k) for k in mark_id_text_map.keys() if str(k).isdigit()
                                ]

                        logger.info(f"LLM 识别到 {len(mark_ids)} 个详情链接")

                        # 3. 提取所选元素的 URL
                        candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                        for candidate in candidates:
                            if self.url_extractor:
                                url = await self.url_extractor.extract_from_element(
                                    candidate, snapshot, nav_steps=self.nav_steps
                                )
                                if url and url not in self.collected_urls:
                                    await self.remember_collected_url(url)

                # 4. 统计更新情况
                current_count = len(self.collected_urls)
                if current_count == last_url_count:
                    no_new_urls_count += 1
                    logger.debug(f"连续 {no_new_urls_count} 次无新 URL")
                else:
                    no_new_urls_count = 0
                    logger.info(f"✓ 当前已收集 {current_count} 个 URL")
                    last_url_count = current_count
                    page_success = True

                # 5. 智能滚动：处理动态加载内容
                if not await smart_scroll(self.page):
                    logger.info("已到达页面底部")
                    break
                scroll_count += 1

        except Exception as e:
            logger.error(f"LLM 收集过程出错: {e}")
            self.rate_controller.apply_penalty()

        return page_success

    def _create_result(self) -> URLCollectorResult:
        """构建最终的收集结果对象

        Returns:
            URLCollectorResult: 包含所有采集到的 URL 和元数据的封装对象
        """
        return URLCollectorResult(
            detail_visits=[],
            common_pattern=None,
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at="",
        )

    @abstractmethod
    async def run(self) -> URLCollectorResult:
        """执行完整的收集流程

        这是一个抽象方法，必须由子类（如 URLCollector 或 BatchCollector）根据具体业务逻辑实现。
        """
        pass
