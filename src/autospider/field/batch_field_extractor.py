"""批量字段提取器

实现完整的字段提取流程：
1. 从 Redis 获取详情页 URL
2. 探索阶段：对多个 URL 进行字段提取
3. 分析阶段：提取公共 XPath 模式
4. 校验阶段：验证公共 XPath 的有效性
5. 生成批量爬取配置
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.config import config
from ..common.logger import get_logger
from ..common.storage import RedisQueueManager

from .models import (
    FieldDefinition,
    BatchExtractionResult,
    PageExtractionRecord,
)
from .field_extractor import FieldExtractor
from .xpath_pattern import (
    FieldXPathExtractor,
    XPathValueLLMValidator,
    validate_xpath_pattern,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = get_logger(__name__)


class BatchFieldExtractor:
    """批量字段提取器

    从 Redis 读取 URL，进行探索、分析、校验，
    最终生成可用于批量爬取的提取配置。
    """

    def __init__(
        self,
        page: "Page",
        fields: list[FieldDefinition],
        redis_manager: RedisQueueManager | None = None,
        explore_count: int = 3,
        validate_count: int = 2,
        output_dir: str = "output",
    ):
        """
        初始化批量字段提取器

        Args:
            page: Playwright 页面对象
            fields: 要提取的字段定义列表
            redis_manager: Redis 管理器（用于读取 URL）
            explore_count: 探索阶段的 URL 数量
            validate_count: 校验阶段的 URL 数量
            output_dir: 输出目录
        """
        self.page = page
        self.fields = fields
        self.redis_manager = redis_manager
        self.explore_count = explore_count
        self.validate_count = validate_count
        self.output_dir = Path(output_dir)

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化组件
        self.field_extractor = FieldExtractor(
            page=page,
            fields=fields,
            output_dir=output_dir,
        )
        self.xpath_extractor = FieldXPathExtractor()
        self.xpath_value_validator = XPathValueLLMValidator()

        # 任务映射：URL -> (stream_id, data_id)
        self.task_mapping: dict[str, tuple[str, str]] = {}

    async def run(self, urls: list[str] | None = None) -> BatchExtractionResult:
        """
        运行批量提取流程

        Args:
            urls: URL 列表（如果提供，则不从 Redis 读取）

        Returns:
            批量提取结果
        """
        logger.info(f"\n{'='*60}")
        logger.info("[BatchFieldExtractor] 开始批量字段提取")
        logger.info(f"[BatchFieldExtractor] 目标字段: {[f.name for f in self.fields]}")
        logger.info(f"[BatchFieldExtractor] 探索数量: {self.explore_count}")
        logger.info(f"[BatchFieldExtractor] 校验数量: {self.validate_count}")
        logger.info(f"{'='*60}\n")

        result = BatchExtractionResult(fields=self.fields)

        # 获取 URL 列表
        if urls is None:
            urls = await self._get_urls_from_redis()

        if not urls:
            logger.info("[BatchFieldExtractor] ✗ 未获取到 URL")
            return result

        total_needed = self.explore_count + self.validate_count
        if len(urls) < total_needed:
            logger.info(f"[BatchFieldExtractor] ⚠ URL 数量不足: {len(urls)} < {total_needed}")
            # 仍然继续，使用所有可用的 URL

        # 分配 URL
        explore_urls = urls[: self.explore_count]
        validate_urls = urls[self.explore_count : self.explore_count + self.validate_count]

        # 阶段 1：探索
        logger.info(f"\n{'='*60}")
        logger.info(f"[BatchFieldExtractor] 阶段 1：探索 ({len(explore_urls)} 个 URL)")
        logger.info(f"{'='*60}\n")

        for i, url in enumerate(explore_urls):
            logger.info(f"\n[BatchFieldExtractor] 探索 {i + 1}/{len(explore_urls)}: {url[:80]}...")
            record = await self.field_extractor.extract_from_url(url)
            result.exploration_records.append(record)
            result.total_urls_explored += 1

            # 打印提取结果摘要
            self._print_record_summary(record)

        # 阶段 2：分析公共 XPath 模式
        logger.info(f"\n{'='*60}")
        logger.info("[BatchFieldExtractor] 阶段 2：分析公共 XPath 模式")
        logger.info(f"{'='*60}\n")

        field_names = [f.name for f in self.fields]
        result.common_xpaths = await self.xpath_extractor.extract_all_common_patterns(
            records=result.exploration_records,
            field_names=field_names,
        )

        # 打印公共 XPath
        for xpath_info in result.common_xpaths:
            logger.info(
                f"[BatchFieldExtractor] ✓ 字段 '{xpath_info.field_name}': {xpath_info.xpath_pattern}"
            )
            logger.info(f"    置信度: {xpath_info.confidence:.2%}")

        if not result.common_xpaths:
            logger.info("[BatchFieldExtractor] ⚠ 未提取到公共 XPath 模式")
            return result

        # 阶段 3：校验
        logger.info(f"\n{'='*60}")
        logger.info(f"[BatchFieldExtractor] 阶段 3：校验公共 XPath ({len(validate_urls)} 个 URL)")
        logger.info(f"{'='*60}\n")

        if validate_urls:
            await self._validate_common_xpaths(result, validate_urls)
        else:
            logger.info("[BatchFieldExtractor] ⚠ 无可用的校验 URL，跳过校验阶段")

        # 保存结果
        await self._save_results(result)

        return result

    async def _get_urls_from_redis(self) -> list[str]:
        """从 Redis 队列获取待处理的 URL"""
        if not self.redis_manager:
            logger.info("[BatchFieldExtractor] ⚠ 未配置 Redis 管理器")
            return []

        try:
            import socket
            import os

            await self.redis_manager.connect()

            # 使用队列模式获取任务
            consumer_name = f"extractor-{socket.gethostname()}-{os.getpid()}"
            total_needed = self.explore_count + self.validate_count

            tasks = await self.redis_manager.fetch_task(
                consumer_name=consumer_name, block_ms=0, count=total_needed  # 非阻塞
            )

            if not tasks:
                logger.info("[BatchFieldExtractor] ⚠ 队列中无待处理任务")
                return []

            urls = []
            for stream_id, data_id, data in tasks:
                url = data.get("url")
                if url:
                    urls.append(url)
                    # 记录任务映射，用于后续 ACK
                    self.task_mapping[url] = (stream_id, data_id)

            logger.info(f"[BatchFieldExtractor] 从 Redis 队列获取了 {len(urls)} 个任务")
            return urls

        except Exception as e:
            logger.info(f"[BatchFieldExtractor] Redis 读取失败: {e}")
            return []

    async def _validate_common_xpaths(
        self,
        result: BatchExtractionResult,
        validate_urls: list[str],
    ) -> None:
        """校验公共 XPath 模式"""
        validation_success_count = 0
        field_def_map = {f.name: f for f in self.fields}
        field_stats: dict[str, dict[str, int]] = {
            x.field_name: {"success": 0, "total": 0} for x in result.common_xpaths
        }
        required_field_names = {f.name for f in self.fields if f.required}

        for i, url in enumerate(validate_urls):
            logger.info(f"\n[BatchFieldExtractor] 校验 {i + 1}/{len(validate_urls)}: {url[:80]}...")

            record = PageExtractionRecord(url=url)
            all_required_fields_ok = True

            # 对每个公共 XPath 进行验证
            for xpath_info in result.common_xpaths:
                field_def = field_def_map.get(xpath_info.field_name)
                success, value = await validate_xpath_pattern(
                    page=self.page,
                    url=url,
                    xpath_pattern=xpath_info.xpath_pattern,
                    data_type=(field_def.data_type if field_def else None),
                    field_name=xpath_info.field_name,
                    field_description=(field_def.description if field_def else ""),
                    llm_validator=self.xpath_value_validator,
                )
                stats = field_stats.setdefault(
                    xpath_info.field_name, {"success": 0, "total": 0}
                )
                stats["total"] += 1

                if success:
                    logger.info(
                        f"    ✓ 字段 '{xpath_info.field_name}': {value[:50] if value else 'N/A'}..."
                    )
                    stats["success"] += 1
                else:
                    logger.info(f"    ✗ 字段 '{xpath_info.field_name}': 验证失败")
                    if xpath_info.field_name in required_field_names:
                        all_required_fields_ok = False

            record.success = all_required_fields_ok
            result.validation_records.append(record)
            result.total_urls_validated += 1

            if all_required_fields_ok:
                validation_success_count += 1

        # 字段级校验：分别判断每个字段 XPath 是否可用
        for xpath_info in result.common_xpaths:
            stats = field_stats.get(xpath_info.field_name, {"success": 0, "total": 0})
            total = stats["total"]
            success = stats["success"]
            success_rate = (success / total) if total else 0.0
            xpath_info.validated = success_rate >= 0.8
            logger.info(
                f"[BatchFieldExtractor] 字段校验率 '{xpath_info.field_name}': "
                f"{success_rate * 100:.0f}% ({success}/{total}) -> "
                f"{'通过' if xpath_info.validated else '不通过'}"
            )

        # 判断整体校验是否成功（必填字段都通过 + 页面级成功率达标）
        if validate_urls:
            page_success_rate = validation_success_count / len(validate_urls)
            required_xpath_ok = all(
                x.validated for x in result.common_xpaths if x.field_name in required_field_names
            )
            result.validation_success = page_success_rate >= 0.8 and required_xpath_ok
            logger.info(f"\n[BatchFieldExtractor] 页面级成功率: {page_success_rate:.0%}")

    async def _save_results(self, result: BatchExtractionResult) -> None:
        """保存提取结果"""
        # 保存提取配置
        config_path = self.output_dir / "extraction_config.json"
        extraction_config = result.to_extraction_config()

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(extraction_config, f, ensure_ascii=False, indent=2)

        logger.info(f"\n[BatchFieldExtractor] 提取配置已保存: {config_path}")

        # 保存详细结果
        detail_path = self.output_dir / "extraction_result.json"
        detail_data = {
            "fields": [
                {
                    "name": f.name,
                    "description": f.description,
                    "required": f.required,
                    "data_type": f.data_type,
                }
                for f in result.fields
            ],
            "common_xpaths": [
                {
                    "field_name": x.field_name,
                    "xpath_pattern": x.xpath_pattern,
                    "confidence": x.confidence,
                    "validated": x.validated,
                    "source_xpaths": x.source_xpaths,
                }
                for x in result.common_xpaths
            ],
            "exploration_records": [
                {
                    "url": r.url,
                    "success": r.success,
                    "fields": [
                        {
                            "field_name": f.field_name,
                            "value": f.value,
                            "xpath": f.xpath,
                            "confidence": f.confidence,
                        }
                        for f in r.fields
                    ],
                }
                for r in result.exploration_records
            ],
            "validation_success": result.validation_success,
            "total_urls_explored": result.total_urls_explored,
            "total_urls_validated": result.total_urls_validated,
            "created_at": result.created_at,
        }

        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(detail_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[BatchFieldExtractor] 详细结果已保存: {detail_path}")

        # ACK 处理成功的任务
        if self.redis_manager and self.task_mapping:
            logger.info("\n[BatchFieldExtractor] 处理任务 ACK...")
            acked_count = 0
            failed_count = 0

            # 处理探索阶段的记录
            for record in result.exploration_records:
                if record.url in self.task_mapping:
                    stream_id, data_id = self.task_mapping[record.url]

                    if record.success:
                        # 成功：发送 ACK
                        await self.redis_manager.ack_task(stream_id)
                        acked_count += 1
                    else:
                        # 失败：标记失败（带重试机制）
                        await self.redis_manager.fail_task(
                            stream_id, data_id, "字段提取失败", max_retries=config.redis.max_retries
                        )
                        failed_count += 1

            # 处理校验阶段的记录
            for record in result.validation_records:
                if record.url in self.task_mapping:
                    stream_id, data_id = self.task_mapping[record.url]

                    if record.success:
                        await self.redis_manager.ack_task(stream_id)
                        acked_count += 1
                    else:
                        await self.redis_manager.fail_task(
                            stream_id,
                            data_id,
                            "XPath 校验失败",
                            max_retries=config.redis.max_retries,
                        )
                        failed_count += 1

            logger.info(f"  ✓ ACK: {acked_count} 个任务")
            logger.info(f"  ✗ FAIL: {failed_count} 个任务")

    def _print_record_summary(self, record: PageExtractionRecord) -> None:
        """打印单页提取结果摘要"""
        status = "✓ 成功" if record.success else "✗ 部分失败"
        logger.info(f"[BatchFieldExtractor] {status} - {record.url[:60]}...")

        for field_result in record.fields:
            if field_result.value:
                logger.info(f"    • {field_result.field_name}: {field_result.value[:40]}...")
            else:
                logger.info(f"    • {field_result.field_name}: (未提取) {field_result.error or ''}")


async def extract_fields_from_urls(
    page: "Page",
    urls: list[str],
    fields: list[FieldDefinition],
    explore_count: int = 3,
    validate_count: int = 2,
    output_dir: str = "output",
) -> BatchExtractionResult:
    """
    便捷函数：从 URL 列表提取字段

    Args:
        page: Playwright 页面对象
        urls: URL 列表
        fields: 字段定义列表
        explore_count: 探索数量
        validate_count: 校验数量
        output_dir: 输出目录

    Returns:
        批量提取结果
    """
    extractor = BatchFieldExtractor(
        page=page,
        fields=fields,
        explore_count=explore_count,
        validate_count=validate_count,
        output_dir=output_dir,
    )

    return await extractor.run(urls=urls)
