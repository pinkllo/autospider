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

from ...common.logger import get_logger
from ...common.storage.persistence import CollectionConfig, ConfigPersistence
from ..collector import (
    URLCollectorResult,
    LLMDecisionMaker,
    NavigationHandler,
)
from ...common.llm import LLMDecider
from ..base.base_collector import BaseCollector

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ...common.storage.redis_manager import RedisQueueManager
    from ...common.channel.base import URLChannel

# 日志器
logger = get_logger(__name__)


class BatchCollector(BaseCollector):
    """批量爬取器

    继承 BaseCollector，基于配置文件执行批量 URL 收集。
    """

    def __init__(
        self,
        page: "Page",
        config_path: str | Path,
        output_dir: str = "output",
        url_channel: "URLChannel | None" = None,
        redis_manager: "RedisQueueManager | None" = None,
    ):
        """初始化批量爬取器

        Args:
            page: Playwright 页面对象
            config_path: 配置文件路径
            output_dir: 输出目录
        """
        self.config_path = Path(config_path)

        # 加载配置以获取 list_url 和 task_description
        self.collection_config: CollectionConfig | None = None
        self._preload_config()

        # 调用基类初始化
        super().__init__(
            page=page,
            list_url=getattr(self, "list_url", ""),
            task_description=getattr(self, "task_description", ""),
            output_dir=output_dir,
            url_channel=url_channel,
            redis_manager=redis_manager,
        )

        # 配置持久化管理器
        self.config_persistence = ConfigPersistence(config_dir=output_dir)

    def _preload_config(self) -> None:
        """预加载配置文件以获取基本信息"""
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.collection_config = CollectionConfig.from_dict(data)
                self.list_url = self.collection_config.list_url
                self.task_description = self.collection_config.task_description
                self.nav_steps = self.collection_config.nav_steps
                self.common_detail_xpath = self.collection_config.common_detail_xpath
            except Exception:
                self.list_url = ""
                self.task_description = ""

    async def run(self) -> URLCollectorResult:
        """运行收集流程（实现基类抽象方法）

        代理到 collect_from_config() 方法。

        Returns:
            收集结果
        """
        return await self.collect_from_config()

    async def collect_from_config(self) -> URLCollectorResult:
        """从配置文件执行批量收集（主流程）

        Returns:
            收集结果
        """
        logger.info("\n[BatchCollector] ===== 开始批量收集 URL =====")

        # 0. 加载配置
        logger.info("\n[Phase 0] 加载配置文件...")
        if not await self._load_config():
            logger.info("[Error] 配置文件加载失败")
            self._save_progress_status(status="FAILED", append_urls=True)
            return self._create_empty_result()

        logger.info("[Phase 0] ✓ 配置加载成功")
        logger.info(f"  - 列表页: {self.list_url}")
        logger.info(f"  - 任务描述: {self.task_description}")
        logger.info(f"  - 导航步骤: {len(self.nav_steps)} 个")
        logger.info(f"  - 公共 XPath: {'已配置' if self.common_detail_xpath else '未配置'}")

        # 0.5 加载历史进度
        previous_progress = self.progress_persistence.load_progress()
        target_page_num = 1
        is_resume = False

        if previous_progress and not self._is_progress_compatible(previous_progress):
            logger.info("\n[断点恢复] 历史进度与当前任务不匹配，忽略旧进度")
            previous_progress = None

        # 0.6 连接 Redis / 本地文件并加载历史 URL（使用基类方法）
        if previous_progress or not self.progress_persistence.has_checkpoint():
            await self._load_previous_urls()

        if previous_progress and previous_progress.current_page_num > 1:
            logger.info(f"\n[断点恢复] 检测到上次中断在第 {previous_progress.current_page_num} 页")
            logger.info(f"[断点恢复] 已收集 {previous_progress.collected_count} 个 URL")
            target_page_num = previous_progress.current_page_num
            is_resume = True

            # 恢复速率控制器状态
            self.rate_controller.current_level = previous_progress.backoff_level
            self.rate_controller.consecutive_success_count = (
                previous_progress.consecutive_success_pages
            )
            logger.info(
                f"[断点恢复] 恢复速率控制状态: 等级={previous_progress.backoff_level}, 连续成功={previous_progress.consecutive_success_pages}"
            )

        # 1. 导航到列表页
        logger.info("\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

        # 初始化处理器
        self._initialize_handlers()

        # 2. 重放导航步骤（如果有）
        if self.nav_steps:
            logger.info("\n[Phase 2] 重放导航步骤...")
            nav_success = await self.navigation_handler.replay_nav_steps(self.nav_steps)
            if not nav_success:
                logger.info("[Warning] 导航步骤重放失败")

            if self.navigation_handler and self.navigation_handler.page is not self.page:
                new_page = self.navigation_handler.page
                new_list_url = self.navigation_handler.list_url or new_page.url
                self._sync_page_references(new_page, list_url=new_list_url)

        # 3. 断点恢复：跳转到目标页
        if target_page_num > 1:
            logger.info(f"\n[Phase 3] 断点恢复：尝试跳转到第 {target_page_num} 页...")
            actual_page = await self._resume_to_target_page(target_page_num)
            self.pagination_handler.current_page_num = actual_page
            logger.info(f"[Phase 3] ✓ 已定位到第 {actual_page} 页，继续收集")

        # 4. 收集阶段
        if self.common_detail_xpath:
            logger.info("\n[Phase 4] 收集阶段：使用公共 xpath 遍历列表页...")
            await self._collect_phase_with_xpath()
        else:
            logger.info("\n[Phase 4] 收集阶段：LLM 遍历列表页...")
            await self._collect_phase_with_llm()

        # 5. 保存结果
        result = self._create_result()
        logger.info("\n[Complete] 收集完成!")
        logger.info(f"  - 收集到 {len(self.collected_urls)} 个详情页 URL")

        await self._save_result(result)
        self._save_progress_status(status="COMPLETED", append_urls=True)

        return result

    async def _load_config(self) -> bool:
        """加载配置文件

        Returns:
            是否加载成功
        """
        if not self.config_path.exists():
            logger.info(f"[Error] 配置文件不存在: {self.config_path}")
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
            logger.info(f"[Error] 加载配置失败: {e}")
            return False

    def _initialize_handlers(self) -> None:
        """初始化各个处理器（覆盖基类方法以添加 LLM 支持）"""
        super()._initialize_handlers()

        # BatchCollector 特有：LLM 模式下需要初始化决策器
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

        # NavigationHandler
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=10,
            decider=LLMDecider() if not self.common_detail_xpath else None,
            screenshots_dir=self.screenshots_dir,
        )

        # 更新 pagination_handler 配置
        if self.pagination_handler:
            self.pagination_handler.llm_decision_maker = self.llm_decision_maker

            if self.collection_config:
                if self.collection_config.pagination_xpath:
                    self.pagination_handler.pagination_xpath = (
                        self.collection_config.pagination_xpath
                    )
                if self.collection_config.jump_widget_xpath:
                    self.pagination_handler.jump_widget_xpath = (
                        self.collection_config.jump_widget_xpath
                    )

    async def _resume_to_target_page(
        self,
        target_page_num: int,
        jump_widget_xpath: dict[str, str] | None = None,
        pagination_xpath: str | None = None,
    ) -> int:
        """使用三阶段策略恢复到目标页（覆盖基类以使用配置中的 xpath）"""
        # 使用配置中的 xpath
        jump_xpath = jump_widget_xpath or (
            self.collection_config.jump_widget_xpath if self.collection_config else None
        )
        pag_xpath = pagination_xpath or (
            self.collection_config.pagination_xpath if self.collection_config else None
        )
        return await super()._resume_to_target_page(target_page_num, jump_xpath, pag_xpath)

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
        logger.info(f"[Save] 结果已保存到: {output_file}")

        # 保存 URL 列表
        urls_file = self.output_dir / "urls.txt"
        urls_file.write_text("\n".join(result.collected_urls), encoding="utf-8")
        logger.info(f"[Save] URL 列表已保存到: {urls_file}")


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
