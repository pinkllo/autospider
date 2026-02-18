"""并发流水线运行器，用于列表采集和字段提取。

该模块实现了生产者-消费者模式，协调 URL 收集过程（列表页）和数据提取过程（详情页）。
主要组件包括：
1. Producer (生产者): 运行 URLCollector 以从列表页收集任务链接。
2. Explorer (探索者): 使用 BatchFieldExtractor 在详情页上探索和生成通用的提取规则（XPath）。
3. Consumer (消费者): 使用生成的 XPath 规则并行处理收集到的所有详情页任务。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from ..common.browser import BrowserSession, shutdown_browser_engine
from ..common.config import config
from ..common.channel.factory import create_url_channel
from ..common.channel.base import URLTask, URLChannel
from ..crawler.explore.url_collector import URLCollector
from ..field import FieldDefinition, BatchFieldExtractor, BatchXPathExtractor
from autospider.common.logger import get_logger

logger = get_logger(__name__)



async def run_pipeline(
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    output_dir: str = "output",
    headless: bool = False,
    explore_count: int | None = None,
    validate_count: int | None = None,
    consumer_concurrency: int | None = None,
    max_pages: int | None = None,
    pipeline_mode: str | None = None,
) -> dict:
    """并发运行列表采集和详情提取。

    Args:
        list_url: 列表页 URL。
        task_description: 任务描述，指导 AI 识别链接和字段。
        fields: 待提取的字段定义列表。
        output_dir: 结果输出目录。
        headless: 是否以无头模式运行浏览器。
        explore_count: 用于探索规则的详情页数量。
        validate_count: 用于验证规则的详情页数量。
        consumer_concurrency: 消费者并发数（每个 worker 使用独立页面）。
        max_pages: 列表页最大翻页次数（可覆盖配置）。
        pipeline_mode: 流水线模式（如 'local' 或 'redis'）。

    Returns:
        包含执行摘要信息的字典。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count
    consumer_workers = max(
        1,
        int(consumer_concurrency or config.pipeline.consumer_concurrency),
    )
    previous_max_pages: int | None = None
    if max_pages is not None:
        previous_max_pages = config.url_collector.max_pages
        config.url_collector.max_pages = int(max_pages)

    channel, redis_manager = create_url_channel(
        mode=pipeline_mode,
        output_dir=output_dir,
    )

    items_path = output_path / "pipeline_extracted_items.jsonl"
    summary_path = output_path / "pipeline_summary.json"

    summary = {
        "list_url": list_url,
        "task_description": task_description,
        "mode": (pipeline_mode or config.pipeline.mode),
        "total_urls": 0,
        "success_count": 0,
        "consumer_concurrency": consumer_workers,
        "started_at": datetime.now().isoformat(),
        "finished_at": "",
        "items_file": str(items_path),
    }

    producer_done = asyncio.Event()
    xpath_ready = asyncio.Event()
    state: dict[str, object] = {"fields_config": None, "error": None}
    explore_tasks: list[URLTask] = []

    # 初始化两个独立的浏览器会话，分别用于列表页和详情页，减少资源竞争
    list_session = BrowserSession(headless=headless)
    detail_session = BrowserSession(headless=headless)

    await list_session.start()
    await detail_session.start()

    async def producer() -> None:
        """生产者：负责从列表页收集详情页链接，并存入通道（Channel）。"""
        try:
            collector = URLCollector(
                page=list_session.page,
                list_url=list_url,
                task_description=task_description,
                explore_count=config.url_collector.explore_count,
                output_dir=output_dir,
                url_channel=channel,
                redis_manager=redis_manager,
            )
            result = await collector.run()
            summary["collected_urls"] = len(result.collected_urls)
        except Exception as exc:  # noqa: BLE001
            state["error"] = f"producer_error: {exc}"
            logger.info(f"[Pipeline] Producer failed: {exc}")
        finally:
            producer_done.set()
            await channel.close()

    async def explorer() -> None:
        """探索者：首先获取适量的任务用于探索和验证 XPath 规则。"""
        needed = explore_count + validate_count
        tasks = await _collect_tasks(
            channel=channel,
            needed=needed,
            producer_done=producer_done,
        )
        explore_tasks.extend(tasks)
        urls = [t.url for t in tasks if t.url]

        if not urls:
            state["error"] = "no_urls_for_exploration"
            logger.info("[Pipeline] No URLs collected for exploration.")
            xpath_ready.set()
            return

        # 使用基础提取器探索页面的共性规则
        extractor = BatchFieldExtractor(
            page=detail_session.page,
            fields=fields,
            explore_count=explore_count,
            validate_count=validate_count,
            output_dir=output_dir,
        )

        result = await extractor.run(urls=urls)
        fields_config = result.to_extraction_config().get("fields", [])
        if not fields_config:
            state["error"] = "no_fields_config"
            logger.info("[Pipeline] No fields config generated from exploration.")
        state["fields_config"] = fields_config
        xpath_ready.set()

    async def consumer() -> None:
        """消费者：在 XPath 规则准备就绪后，大规模批量处理剩余任务。"""
        await xpath_ready.wait()
        fields_config = state.get("fields_config") or []
        if not fields_config:
            # 如果没有生成规则，直接标记所有已领取的任务失败
            await _fail_tasks(explore_tasks, "xpath_config_missing")
            return

        logger.info(f"[Pipeline] Consumer workers: {consumer_workers}")

        queue_size = max(
            consumer_workers * 2,
            consumer_workers * config.pipeline.batch_flush_size,
        )
        task_queue: asyncio.Queue[URLTask | None] = asyncio.Queue(maxsize=queue_size)
        summary_lock = asyncio.Lock()

        async def feeder() -> None:
            # 先处理探索阶段已经领取的任务
            for task in explore_tasks:
                await task_queue.put(task)

            # 再持续从 channel 拉取新任务
            while True:
                batch = await channel.fetch(
                    max_items=config.pipeline.batch_fetch_size,
                    timeout_s=config.pipeline.fetch_timeout_s,
                )
                if not batch:
                    if producer_done.is_set():
                        break
                    continue
                for task in batch:
                    await task_queue.put(task)

            # 通知 worker 退出
            for _ in range(consumer_workers):
                await task_queue.put(None)

        async def worker(_worker_id: int) -> None:
            session = BrowserSession(headless=headless)
            await session.start()
            extractor = BatchXPathExtractor(
                page=session.page,
                fields_config=fields_config,
                output_dir=output_dir,
            )

            try:
                while True:
                    task = await task_queue.get()
                    if task is None:
                        return
                    await _process_task(
                        extractor=extractor,
                        task=task,
                        items_path=items_path,
                        summary=summary,
                        summary_lock=summary_lock,
                    )
            finally:
                await session.stop()

        await asyncio.gather(
            feeder(),
            *(worker(i + 1) for i in range(consumer_workers)),
        )

    try:
        await asyncio.gather(
            producer(),
            explorer(),
            consumer(),
        )
    finally:
        if previous_max_pages is not None:
            config.url_collector.max_pages = previous_max_pages
        summary["finished_at"] = datetime.now().isoformat()
        if state.get("error"):
            summary["error"] = state.get("error")
        _write_summary(summary_path, summary)
        await list_session.stop()
        await detail_session.stop()
        await shutdown_browser_engine()

    return summary


async def _collect_tasks(
    channel: URLChannel,
    needed: int,
    producer_done: asyncio.Event,
) -> list[URLTask]:
    """从通道中收集指定数量的任务。

    该函数会持续从通道 fetch 任务，直到达到所需数量或生产者已完成且通道为空。

    Args:
        channel: 任务分发通道。
        needed: 需要收集的任务数量。
        producer_done: 生产者完成信号。

    Returns:
        收集到的任务列表。
    """
    tasks: list[URLTask] = []
    while len(tasks) < needed:
        # 批量获取任务以提高效率
        batch = await channel.fetch(
            max_items=needed - len(tasks),
            timeout_s=config.pipeline.fetch_timeout_s,
        )
        if not batch:
            # 如果没有获取到任务，且生产者已停止，则退出
            if producer_done.is_set():
                break
            continue
        tasks.extend(batch)
    return tasks


async def _process_task(
    extractor: BatchXPathExtractor,
    task: URLTask,
    items_path: Path,
    summary: dict,
    summary_lock: asyncio.Lock,
) -> None:
    """执行单条任务提取并保存结果。

    Args:
        extractor: XPath 提取器实例。
        task: 待处理任务。
        items_path: 结果保存的文件路径 (JSONL)。
        summary: 流水线汇总统计信息字典。
        summary_lock: 写文件与更新汇总时使用的互斥锁。
    """
    url = (task.url or "").strip()
    if not url:
        await task.fail_task("empty_url")
        return

    try:
        record = await extractor._extract_from_url(url)
    except Exception as exc:  # noqa: BLE001
        # 兜底处理：确保单条失败不会中断整条流水线
        async with summary_lock:
            _append_jsonl(
                items_path,
                {
                    "url": url,
                    "_error": f"extractor_exception: {exc}",
                },
            )
            summary["total_urls"] += 1
        await task.fail_task(f"extractor_exception: {exc}")
        return

    # 将提取到的字段映射为简单的键值对字典
    item = {"url": record.url}
    for field_result in record.fields:
        item[field_result.field_name] = field_result.value

    # 将结果追加到 JSONL 文件并更新统计（并发下需要互斥）
    async with summary_lock:
        _append_jsonl(items_path, item)
        summary["total_urls"] += 1
        if record.success:
            summary["success_count"] += 1

    if record.success:
        # 标记任务成功（Redis 模式下会进行 ACK）
        await task.ack_task()
    else:
        # 标记任务失败并记录原因
        reason = _build_error_reason(record)
        await task.fail_task(reason)


async def _fail_tasks(tasks: list[URLTask], reason: str) -> None:
    """批量标记任务失败。

    Args:
        tasks: 需要标记失败的任务列表。
        reason: 失败原因描述。
    """
    for task in tasks:
        await task.fail_task(reason)


def _build_error_reason(record) -> str:
    """从提取记录中构建错误原因字符串。

    遍历所有字段的提取结果，收集其中的错误信息并组合成一个字符串。
    """
    errors = []
    for field_result in record.fields:
        if field_result.error:
            errors.append(field_result.error)
    return "; ".join(errors) if errors else "extraction_failed"


def _append_jsonl(path: Path, item: dict) -> None:
    """向 JSONL 文件追加一条结果记录。

    Args:
        path: 文件路径。
        item: 要保存的字典对象。
    """
    payload = json.dumps(item, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def _write_summary(path: Path, summary: dict) -> None:
    """将执行摘要写入 JSON 文件。

    Args:
        path: 文件路径。
        summary: 汇总信息字典。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
