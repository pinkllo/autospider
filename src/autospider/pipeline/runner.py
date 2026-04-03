"""并发流水线运行器，用于列表采集和字段提取。

该模块实现了生产者-消费者模式，协调 URL 收集过程（列表页）和数据提取过程（详情页）。
主要组件包括：
1. Producer (生产者): 运行 URLCollector 以从列表页收集任务链接。
2. Explorer (探索者): 使用 BatchFieldExtractor 在详情页上探索和生成通用的提取规则（XPath）。
3. Consumer (消费者): 使用生成的 XPath 规则并行处理收集到的所有详情页任务。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..common.browser.intervention import BrowserInterventionRequired

from ..common.browser import BrowserSession
from ..common.config import config
from ..common.experience import SkillRuntime
from ..common.channel.factory import create_url_channel
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed
from ..common.channel.base import URLTask, URLChannel
from ..crawler.explore.url_collector import URLCollector
from ..domain.fields import FieldDefinition
from ..field import BatchFieldExtractor, BatchXPathExtractor
from autospider.common.logger import get_logger
from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


def _is_valid_xpath(xpath: object) -> bool:
    """判断字段配置中的 XPath 是否有效。"""
    return isinstance(xpath, str) and xpath.strip().startswith("/")


def _prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    """清洗字段配置并返回 (有效字段, 缺失 XPath 的必填字段, 缺失 XPath 的可选字段)。"""
    valid_fields: list[dict] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for field in fields_config:
        if not isinstance(field, dict):
            continue

        field_name = str(field.get("name") or "").strip() or "<unknown>"
        xpath = field.get("xpath")
        required = bool(field.get("required", True))
        data_type = str(field.get("data_type") or "").strip().lower()
        source = str(field.get("extraction_source") or "").strip().lower()
        fixed_value = field.get("fixed_value")

        if _is_valid_xpath(xpath):
            normalized = dict(field)
            normalized["xpath"] = str(xpath).strip()
            valid_fields.append(normalized)
            continue

        if source in {"constant", "subtask_context"}:
            value = "" if fixed_value is None else str(fixed_value).strip()
            if value:
                normalized = dict(field)
                normalized["xpath"] = None
                normalized["extraction_source"] = source
                normalized["fixed_value"] = value
                valid_fields.append(normalized)
                continue

        # URL 字段可直接从任务 URL 回填，避免“必填但无 XPath”阻断整条流水线
        if data_type == "url":
            normalized = dict(field)
            normalized["xpath"] = None
            normalized["extraction_source"] = "task_url"
            valid_fields.append(normalized)
            continue

        if required:
            missing_required.append(field_name)
        else:
            missing_optional.append(field_name)

    return valid_fields, missing_required, missing_optional


def _set_state_error(state: dict[str, object], error: str) -> None:
    """仅在首次出错时写入状态，避免覆盖更早的根因。"""
    if not state.get("error"):
        state["error"] = error


def _find_output_draft_skill(list_url: str, output_dir: str) -> tuple[str, Path] | None:
    """在当前输出目录附近查找 planner 生成的 draft Skill。"""
    domain = urlparse(str(list_url or "")).netloc.strip().lower()
    if not domain:
        return None

    output_path = Path(output_dir)
    candidates = [
        output_path / "draft_skills" / domain / "SKILL.md",
        output_path.parent / "draft_skills" / domain / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return domain, candidate
    return None


def _cleanup_output_draft_skill(list_url: str, output_dir: str) -> None:
    """移除 output 中的 draft Skill，避免最终产物重复保留。"""
    located = _find_output_draft_skill(list_url, output_dir)
    if located is None:
        return

    _, draft_path = located
    try:
        draft_path.unlink(missing_ok=True)
        logger.info("[Pipeline] 已清理输出目录中的 Draft Skill: %s", draft_path)
    except Exception as exc:
        logger.debug("[Pipeline] 清理 Draft Skill 失败（不影响主流程）: %s", exc)


def _load_validation_failures(output_path: Path) -> list[dict]:
    """从 extraction_result.json 读取校验失败记录。"""
    detail_path = output_path / "extraction_result.json"
    if not detail_path.exists():
        return []
    try:
        payload = json.loads(detail_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    failures = payload.get("validation_failures", [])
    return list(failures) if isinstance(failures, list) else []


def _classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
) -> dict[str, object]:
    """统一产出 pipeline 执行状态、结果状态和可复用等级。"""
    failed_count = max(total_urls - success_count, 0)
    success_rate = (success_count / total_urls) if total_urls > 0 else 0.0
    validation_failure_count = len(validation_failures)
    execution_state = "failed" if state_error else "completed"

    if success_count <= 0 or total_urls <= 0:
        outcome_state = "failed"
    elif not state_error and success_rate > 0.7 and validation_failure_count == 0:
        outcome_state = "success"
    else:
        outcome_state = "partial_success"

    if (
        total_urls > 0
        and success_count > 0
        and not state_error
        and success_rate > 0.7
        and validation_failure_count == 0
    ):
        promotion_state = "reusable"
    elif success_count > 0:
        promotion_state = "diagnostic_only"
    else:
        promotion_state = "rejected"

    return {
        "execution_state": execution_state,
        "outcome_state": outcome_state,
        "promotion_state": promotion_state,
        "success_rate": round(success_rate, 4),
        "failed_count": failed_count,
        # 现阶段按页面级成功率近似必填字段成功率，保持判定口径一致。
        "required_field_success_rate": round(success_rate, 4),
        "validation_failure_count": validation_failure_count,
    }


def _should_promote_skill(
    *,
    state: dict[str, object],
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    """判断本次运行是否满足正式 skill 的提升条件。"""
    if str(summary.get("promotion_state") or "").strip().lower() == "reusable":
        return True

    classified = _classify_pipeline_result(
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        state_error=state.get("error"),
        validation_failures=validation_failures,
    )
    return bool(classified.get("promotion_state") == "reusable")


def _strip_draft_markers_from_skill_content(content: str) -> str:
    """将提升到 .agents/skills 的 draft Skill 正文去除草稿标记。"""
    text = str(content or "")
    if not text.strip():
        return text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except Exception:
                frontmatter = None
            if isinstance(frontmatter, dict):
                description = str(frontmatter.get("description") or "").strip()
                if description:
                    frontmatter["description"] = description.replace("（草稿）", "").replace("草稿", "").strip()
                rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
                text = f"---\n{rendered}\n---{parts[2]}"

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        if line.startswith("# ") and "（草稿）" in line:
            line = line.replace("（草稿）", "")
        if line.startswith("- **状态**:") and ("draft" in line.lower() or "草稿" in line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    if cleaned:
        cleaned += "\n"
    return cleaned


def _promote_output_draft_skill(list_url: str, output_dir: str) -> Path | None:
    """将 output 中的 draft Skill 提升到 .agents/skills，作为流程结束后的最终回填。"""
    located = _find_output_draft_skill(list_url, output_dir)
    if located is None:
        return None

    try:
        from ..common.experience import SkillStore

        domain, draft_path = located
        content = draft_path.read_text(encoding="utf-8")
        if not content.strip():
            return None

        cleaned_content = _strip_draft_markers_from_skill_content(content)
        result_path = SkillStore().save(domain, cleaned_content)
        draft_path.unlink(missing_ok=True)
        logger.info("[Pipeline] Draft Skill 已迁移到 skills 目录: %s", result_path)
        return result_path
    except Exception as exc:
        logger.debug("[Pipeline] Draft Skill 迁移失败（不影响主流程）: %s", exc)
        return None



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
    target_url_count: int | None = None,
    pipeline_mode: str | None = None,
    redis_key_prefix: str | None = None,
    guard_intervention_mode: str = "blocking",
    guard_thread_id: str = "",
    selected_skills: list[dict[str, str]] | None = None,
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
        target_url_count: 目标采集 URL 数量（可覆盖配置）。
        pipeline_mode: 流水线模式（如 'local' 或 'redis'）。
        redis_key_prefix: redis 模式下的 key 前缀（可选，用于队列隔离）。

    Returns:
        包含执行摘要信息的字典。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    execution_id = _build_execution_id(
        list_url=list_url,
        task_description=task_description,
        fields=fields,
        target_url_count=target_url_count,
        max_pages=max_pages,
        pipeline_mode=pipeline_mode,
        thread_id=guard_thread_id,
    )

    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count
    consumer_workers = max(
        1,
        int(consumer_concurrency or config.pipeline.consumer_concurrency),
    )

    channel, redis_manager = create_url_channel(
        mode=pipeline_mode,
        output_dir=output_dir,
        redis_key_prefix=redis_key_prefix,
    )

    items_path = output_path / "pipeline_extracted_items.jsonl"
    summary_path = output_path / "pipeline_summary.json"
    staging_dir = output_path / ".pipeline_items"
    manifest_path = output_path / "pipeline_execution.json"
    _prepare_pipeline_workspace(
        output_path=output_path,
        staging_dir=staging_dir,
        items_path=items_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        execution_id=execution_id,
        list_url=list_url,
        task_description=task_description,
    )
    staged_records = _load_staged_records(staging_dir)
    skill_runtime = SkillRuntime()

    summary = {
        "run_id": execution_id,
        "list_url": list_url,
        "task_description": task_description,
        "mode": (pipeline_mode or config.pipeline.mode),
        "total_urls": 0,
        "success_count": 0,
        "consumer_concurrency": consumer_workers,
        "target_url_count": target_url_count,
        "items_file": str(items_path),
        "summary_file": str(summary_path),
        "execution_id": execution_id,
    }

    producer_done = asyncio.Event()
    xpath_ready = asyncio.Event()
    state: dict[str, object] = {"fields_config": None, "error": None}
    explore_tasks: list[URLTask] = []
    url_only_mode = len(fields) == 0

    # 初始化进度追踪器（进度走 Redis，结果走 PG）
    tracker = TaskProgressTracker(execution_id)

    # 初始化两个独立的浏览器会话，分别用于列表页和详情页，减少资源竞争
    list_session = BrowserSession(
        headless=headless,
        guard_intervention_mode=guard_intervention_mode,
        guard_thread_id=guard_thread_id,
    )
    detail_session = BrowserSession(
        headless=headless,
        guard_intervention_mode=guard_intervention_mode,
        guard_thread_id=guard_thread_id,
    )

    await list_session.start()
    await detail_session.start()

    async def producer() -> None:
        """生产者：负责从列表页收集详情页链接，并存入通道（Channel）。"""
        try:
            collector = URLCollector(
                page=list_session.page,
                list_url=list_url,
                task_description=task_description,
                explore_count=explore_count,
                output_dir=output_dir,
                url_channel=channel,
                redis_manager=redis_manager,
                target_url_count=target_url_count,
                max_pages=max_pages,
                persist_progress=False,
                skill_runtime=skill_runtime,
                selected_skills=selected_skills,
            )
            result = await collector.run()
            summary["collected_urls"] = len(result.collected_urls)
            await tracker.set_total(len(result.collected_urls))

        except BrowserInterventionRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            _set_state_error(state, f"producer_error: {exc}")
            logger.info(f"[Pipeline] Producer failed: {exc}")
        finally:
            producer_done.set()
            await channel.close()

    async def explorer() -> None:
        """探索者：首先获取适量的任务用于探索和验证 XPath 规则。"""
        if url_only_mode:
            # 兼容“仅收集 URL”场景：未提供字段定义时，自动回填 URL 字段，
            # 避免因无 XPath 配置导致 consumer 被整体阻断。
            logger.info("[Pipeline] 未提供字段定义，启用 URL-only 模式。")
            state["fields_config"] = [
                {
                    "name": "url",
                    "description": "详情页 URL",
                    "xpath": None,
                    "required": True,
                    "data_type": "url",
                    "extraction_source": "task_url",
                }
            ]
            xpath_ready.set()
            return

        needed = explore_count + validate_count
        tasks = await _collect_tasks(
            channel=channel,
            needed=needed,
            producer_done=producer_done,
        )
        explore_tasks.extend(tasks)
        urls = [t.url for t in tasks if t.url]

        if not urls:
            _set_state_error(state, "no_urls_for_exploration")
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
            skill_runtime=skill_runtime,
        )

        result = await extractor.run(urls=urls)
        raw_fields_config = result.to_extraction_config().get("fields", [])
        fields_config, missing_required, missing_optional = _prepare_fields_config(
            raw_fields_config
        )

        if missing_optional:
            logger.info(
                f"[Pipeline] Optional fields missing XPath and will be skipped: {missing_optional}"
            )

        if missing_required:
            _set_state_error(
                state,
                f"required_fields_xpath_missing: {', '.join(missing_required)}",
            )
            logger.info(f"[Pipeline] Required fields missing XPath: {missing_required}")
            # 必填字段缺失时直接阻断消费阶段，避免输出“看似成功但关键字段为空”的结果
            state["fields_config"] = []
            xpath_ready.set()
            return
        elif not fields_config:
            _set_state_error(state, "no_valid_fields_config")
            logger.info("[Pipeline] No valid fields config generated from exploration.")
        state["fields_config"] = fields_config
        xpath_ready.set()

    async def consumer() -> None:
        """消费者：在 XPath 规则准备就绪后，大规模批量处理剩余任务。"""
        await xpath_ready.wait()
        fields_config = state.get("fields_config") or []
        if not fields_config:
            # 如果没有生成规则，直接标记所有已领取的任务失败
            fail_reason = str(state.get("error") or "xpath_config_missing")
            await _fail_tasks(explore_tasks, fail_reason)
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
            session = BrowserSession(
                headless=headless,
                guard_intervention_mode=guard_intervention_mode,
                guard_thread_id=guard_thread_id,
            )
            await session.start()
            extractor = BatchXPathExtractor(
                page=session.page,
                fields_config=fields_config,
                output_dir=output_dir,
                skill_runtime=skill_runtime,
            )

            try:
                while True:
                    task = await task_queue.get()
                    if task is None:
                        return
                    await _process_task(
                        extractor=extractor,
                        task=task,
                        staging_dir=staging_dir,
                        staged_records=staged_records,
                        summary_lock=summary_lock,
                        tracker=tracker,
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

        if state.get("error"):
            summary["error"] = state.get("error")
        committed_records = _load_staged_records(staging_dir)
        committed_summary = _build_summary_from_staged_records(committed_records)
        summary["total_urls"] = committed_summary["total_urls"]
        summary["success_count"] = committed_summary["success_count"]
        validation_failures = _load_validation_failures(output_path)
        summary.update(
            _classify_pipeline_result(
                total_urls=summary["total_urls"],
                success_count=summary["success_count"],
                state_error=state.get("error"),
                validation_failures=validation_failures,
            )
        )
        _commit_items_file(items_path, committed_records)
        _write_summary(summary_path, summary)
        # 标记进度追踪完成
        final_status = str(summary.get("execution_state") or "completed")
        await tracker.mark_done(final_status)

        # 经验沉淀：仅高质量成功运行会写入正式 Skill
        sedimented_skill_path = _try_sediment_skill(
            list_url=list_url,
            task_description=task_description,
            fields=fields,
            state=state,
            summary=summary,
            output_dir=output_dir,
        )
        if sedimented_skill_path:
            _cleanup_output_draft_skill(list_url=list_url, output_dir=output_dir)

        await list_session.stop()
        await detail_session.stop()

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
    staging_dir: Path,
    staged_records: dict[str, dict],
    summary_lock: asyncio.Lock,
    tracker: TaskProgressTracker | None = None,
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

    async with summary_lock:
        existing_record = staged_records.get(url)

    if existing_record is not None:
        await _finalize_task_from_staged_record(task, existing_record)
        return

    try:
        record = await extractor._extract_from_url(url)
    except BrowserInterventionRequired:
        raise
    except Exception as exc:  # noqa: BLE001
        staged_record = _build_staged_record(
            url=url,
            item={
                "url": url,
                "_error": f"extractor_exception: {exc}",
            },
            success=False,
            failure_reason=f"extractor_exception: {exc}",
        )
    else:
        item = {"url": record.url}
        for field_result in record.fields:
            item[field_result.field_name] = field_result.value

        if record.success:
            staged_record = _build_staged_record(
                url=url,
                item=item,
                success=True,
                failure_reason="",
            )
        else:
            staged_record = _build_staged_record(
                url=url,
                item=item,
                success=False,
                failure_reason=_build_error_reason(record),
            )

    async with summary_lock:
        _write_staged_record(staging_dir, staged_record)
        staged_records[url] = staged_record

    await _finalize_task_from_staged_record(task, staged_record)

    # 同步进度到 Redis
    if tracker:
        if staged_record.get("success"):
            await tracker.record_success(url)
        else:
            await tracker.record_failure(url, staged_record.get("failure_reason", ""))


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


def _build_execution_id(
    *,
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    target_url_count: int | None,
    max_pages: int | None,
    pipeline_mode: str | None,
    thread_id: str,
) -> str:
    payload = {
        "list_url": list_url,
        "task_description": task_description,
        "fields": [field.model_dump(mode="python") for field in fields],
        "target_url_count": target_url_count,
        "max_pages": max_pages,
        "pipeline_mode": pipeline_mode,
        "thread_id": thread_id,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]



def _prepare_pipeline_workspace(
    *,
    output_path: Path,
    staging_dir: Path,
    items_path: Path,
    summary_path: Path,
    manifest_path: Path,
    execution_id: str,
    list_url: str,
    task_description: str,
) -> None:
    previous_execution_id = ""
    if manifest_path.exists():
        try:
            previous_execution_id = str(
                json.loads(manifest_path.read_text(encoding="utf-8")).get("execution_id") or ""
            )
        except Exception:
            previous_execution_id = ""

    if previous_execution_id and previous_execution_id != execution_id:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if items_path.exists():
            items_path.unlink(missing_ok=True)
        if summary_path.exists():
            summary_path.unlink(missing_ok=True)

    output_path.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "execution_id": execution_id,
        "list_url": list_url,
        "task_description": task_description,
        "updated_at": "",
    }
    write_json_idempotent(manifest_path, manifest, identity_keys=("execution_id", "list_url", "task_description"))



def _staged_record_path(staging_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return staging_dir / f"{digest}.json"



def _build_staged_record(
    *,
    url: str,
    item: dict,
    success: bool,
    failure_reason: str,
) -> dict:
    return {
        "url": url,
        "success": bool(success),
        "failure_reason": str(failure_reason or ""),
        "item": dict(item),
    }



def _write_staged_record(staging_dir: Path, record: dict) -> None:
    path = _staged_record_path(staging_dir, str(record.get("url") or ""))
    _write_json_atomic(path, record)



def _load_staged_records(staging_dir: Path) -> dict[str, dict]:
    if not staging_dir.exists():
        return {}

    records: dict[str, dict] = {}
    for record_file in sorted(staging_dir.glob("*.json")):
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = str(record.get("url") or "").strip()
        item = record.get("item")
        if not url or not isinstance(item, dict):
            continue
        records[url] = {
            "url": url,
            "success": bool(record.get("success", False)),
            "failure_reason": str(record.get("failure_reason") or ""),
            "item": dict(item),
        }
    return records



def _build_summary_from_staged_records(records: dict[str, dict]) -> dict[str, int]:
    total_urls = len(records)
    success_count = sum(1 for record in records.values() if bool(record.get("success")))
    return {
        "total_urls": total_urls,
        "success_count": success_count,
    }



def _commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    payload_lines = [
        json.dumps(record["item"], ensure_ascii=False)
        for _, record in sorted(records.items(), key=lambda pair: pair[0])
    ]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    write_text_if_changed(items_path, payload)


async def _finalize_task_from_staged_record(task: URLTask, staged_record: dict) -> None:
    if bool(staged_record.get("success")):
        await task.ack_task()
        return
    reason = str(staged_record.get("failure_reason") or "extraction_failed")
    await task.fail_task(reason)



def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)



def _write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)




def _write_summary(path: Path, summary: dict) -> None:
    """将执行摘要写入 JSON 文件。"""
    write_json_idempotent(
        path,
        summary,
        identity_keys=("run_id", "list_url", "task_description"),
        volatile_keys={"created_at", "updated_at", "timestamp", "last_updated"},
    )


def _try_sediment_skill(
    *,
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    state: dict[str, object],
    summary: dict,
    output_dir: str,
) -> Path | None:
    """尝试将本次 Pipeline 执行的经验沉淀为 Spider Skill，不影响主流程。"""
    try:
        from ..common.experience import SkillSedimenter

        # 从 output_dir 中读取已保存的配置文件
        output_path = Path(output_dir)

        collection_config: dict = {}
        cc_path = output_path / "collection_config.json"
        if cc_path.exists():
            try:
                collection_config = json.loads(cc_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        extraction_config: dict = {}
        ec_path = output_path / "extraction_config.json"
        if ec_path.exists():
            try:
                extraction_config = json.loads(ec_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 读取校验失败记录
        validation_failures = _load_validation_failures(output_path)

        if not _should_promote_skill(
            state=state,
            summary=summary,
            validation_failures=validation_failures,
        ):
            logger.info("[Pipeline] 本次运行未达到 Skill 提升条件，保留 draft skill")
            return None

        # 字段定义转为 dict 列表
        fields_dicts = [f.model_dump() for f in fields]

        # 读取 DFS 知识文档（Worker 在子目录运行，plan_knowledge.md 在父目录）
        plan_knowledge = ""
        for candidate in [output_path / "plan_knowledge.md", output_path.parent / "plan_knowledge.md"]:
            if candidate.exists():
                try:
                    plan_knowledge = candidate.read_text(encoding="utf-8")
                    break
                except Exception:
                    pass

        sedimenter = SkillSedimenter()
        result_path = sedimenter.sediment_from_pipeline_result(
            list_url=list_url,
            task_description=task_description,
            fields=fields_dicts,
            collection_config=collection_config,
            extraction_config=extraction_config,
            summary=summary,
            validation_failures=validation_failures,
            plan_knowledge=plan_knowledge,
            status="validated",
        )

        if result_path:
            logger.info("[Pipeline] 经验已沉淀为 Skill: %s", result_path)
        return result_path

    except Exception as exc:
        logger.debug("[Pipeline] 经验沉淀失败（不影响主流程）: %s", exc)
        return None

