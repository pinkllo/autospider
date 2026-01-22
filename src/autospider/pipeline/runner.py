"""Concurrent pipeline runner for list collection and field extraction."""

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


async def run_pipeline(
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    output_dir: str = "output",
    headless: bool = False,
    explore_count: int | None = None,
    validate_count: int | None = None,
    pipeline_mode: str | None = None,
) -> dict:
    """Run list collection and detail extraction concurrently."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count

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
        "started_at": datetime.now().isoformat(),
        "finished_at": "",
        "items_file": str(items_path),
    }

    producer_done = asyncio.Event()
    xpath_ready = asyncio.Event()
    state: dict[str, object] = {"fields_config": None, "error": None}
    explore_tasks: list[URLTask] = []

    list_session = BrowserSession(headless=headless)
    detail_session = BrowserSession(headless=headless)

    await list_session.start()
    await detail_session.start()

    async def producer() -> None:
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
            print(f"[Pipeline] Producer failed: {exc}")
        finally:
            producer_done.set()
            await channel.close()

    async def explorer() -> None:
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
            print("[Pipeline] No URLs collected for exploration.")
            xpath_ready.set()
            return

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
            print("[Pipeline] No fields config generated from exploration.")
        state["fields_config"] = fields_config
        xpath_ready.set()

    async def consumer() -> None:
        await xpath_ready.wait()
        fields_config = state.get("fields_config") or []
        if not fields_config:
            await _fail_tasks(explore_tasks, "xpath_config_missing")
            return

        extractor = BatchXPathExtractor(
            page=detail_session.page,
            fields_config=fields_config,
            output_dir=output_dir,
        )

        await _process_tasks(
            extractor=extractor,
            tasks=explore_tasks,
            items_path=items_path,
            summary=summary,
        )

        buffer: list[URLTask] = []
        while True:
            batch = await channel.fetch(
                max_items=config.pipeline.batch_fetch_size,
                timeout_s=config.pipeline.fetch_timeout_s,
            )
            if not batch:
                if producer_done.is_set():
                    break
                continue

            buffer.extend(batch)

            if len(buffer) >= config.pipeline.batch_flush_size:
                await _process_tasks(
                    extractor=extractor,
                    tasks=buffer,
                    items_path=items_path,
                    summary=summary,
                )
                buffer = []

        if buffer:
            await _process_tasks(
                extractor=extractor,
                tasks=buffer,
                items_path=items_path,
                summary=summary,
            )

    try:
        await asyncio.gather(
            producer(),
            explorer(),
            consumer(),
        )
    finally:
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
    tasks: list[URLTask] = []
    while len(tasks) < needed:
        batch = await channel.fetch(
            max_items=needed - len(tasks),
            timeout_s=config.pipeline.fetch_timeout_s,
        )
        if not batch:
            if producer_done.is_set():
                break
            continue
        tasks.extend(batch)
    return tasks


async def _process_tasks(
    extractor: BatchXPathExtractor,
    tasks: list[URLTask],
    items_path: Path,
    summary: dict,
) -> None:
    for task in tasks:
        url = task.url
        if not url:
            continue

        record = await extractor._extract_from_url(url)
        item = {"url": record.url}
        for field_result in record.fields:
            item[field_result.field_name] = field_result.value

        _append_jsonl(items_path, item)
        summary["total_urls"] += 1

        if record.success:
            summary["success_count"] += 1
            await task.ack_task()
        else:
            reason = _build_error_reason(record)
            await task.fail_task(reason)


async def _fail_tasks(tasks: list[URLTask], reason: str) -> None:
    for task in tasks:
        await task.fail_task(reason)


def _build_error_reason(record) -> str:
    errors = []
    for field_result in record.fields:
        if field_result.error:
            errors.append(field_result.error)
    return "; ".join(errors) if errors else "extraction_failed"


def _append_jsonl(path: Path, item: dict) -> None:
    payload = json.dumps(item, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
