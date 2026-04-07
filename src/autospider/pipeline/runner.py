"""并发流水线运行器，用于列表采集和字段提取。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from ..common.browser import BrowserSession
from ..common.browser.intervention import BrowserInterventionRequired
from ..common.channel.base import URLChannel, URLTask
from ..common.channel.factory import create_url_channel
from ..common.config import config
from ..common.experience import SkillRuntime
from ..contracts import ExecutionContext, PipelineMode, TaskIdentity
from ..crawler.explore.url_collector import URLCollector
from ..domain.fields import FieldDefinition
from ..field import DetailPageWorker
from autospider.common.logger import get_logger
from .finalization import (
    PipelineFinalizationContext,
    PipelineFinalizationDependencies,
    PipelineFinalizer,
    build_execution_id as _build_execution_id_impl,
    build_record_summary as _build_record_summary_impl,
    build_run_record as _build_run_record_impl,
    classify_pipeline_result as _classify_pipeline_result_impl,
    commit_items_file as _commit_items_file_impl,
    find_output_draft_skill as _find_output_draft_skill_impl,
    finalize_task_from_record as _finalize_task_from_record_impl,
    load_persisted_run_records as _load_persisted_run_records_impl,
    persist_pipeline_run as _persist_pipeline_run_impl,
    promote_staged_output as _promote_staged_output_impl,
    prepare_fields_config as _prepare_fields_config_impl,
    prepare_pipeline_output as _prepare_pipeline_output_impl,
    should_promote_skill as _should_promote_skill_impl,
    strip_draft_markers_from_skill_content as _strip_draft_markers_from_skill_content_impl,
    write_summary as _write_summary_impl,
)
from .orchestration import (
    PipelineRuntimeContext,
    PipelineRuntimeDependencies,
    PipelineSessionBundle,
    create_pipeline_services,
)
from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


def _prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    return _prepare_fields_config_impl(fields_config)


def _find_output_draft_skill(list_url: str, output_dir: str):
    return _find_output_draft_skill_impl(list_url, output_dir)


def _classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
    terminal_reason: str = "",
) -> dict[str, object]:
    return _classify_pipeline_result_impl(
        total_urls=total_urls,
        success_count=success_count,
        state_error=state_error,
        validation_failures=validation_failures,
        terminal_reason=terminal_reason,
    )


def _should_promote_skill(
    *,
    state: dict[str, object],
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    return _should_promote_skill_impl(
        state=state,
        summary=summary,
        validation_failures=validation_failures,
    )


def _strip_draft_markers_from_skill_content(content: str) -> str:
    return _strip_draft_markers_from_skill_content_impl(content)


def _build_execution_id(
    *,
    list_url: str,
    task_description: str,
    execution_brief: dict[str, Any] | None,
    fields: list[FieldDefinition],
    target_url_count: int | None,
    max_pages: int | None,
    pipeline_mode: str | None,
    thread_id: str,
    page_state_signature: str = "",
    anchor_url: str | None = None,
    variant_label: str | None = None,
) -> str:
    return _build_execution_id_impl(
        list_url=list_url,
        task_description=task_description,
        execution_brief=dict(execution_brief or {}),
        fields=fields,
        target_url_count=target_url_count,
        max_pages=max_pages,
        pipeline_mode=pipeline_mode,
        thread_id=thread_id,
        page_state_signature=page_state_signature,
        anchor_url=anchor_url,
        variant_label=variant_label,
    )


def _generate_execution_id() -> str:
    return f"exec_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def _prepare_pipeline_output(
    *,
    output_path: Path,
    items_path: Path,
    summary_path: Path,
) -> None:
    _prepare_pipeline_output_impl(
        output_path=output_path,
        items_path=items_path,
        summary_path=summary_path,
    )


def _build_run_record(
    *,
    url: str,
    item: dict,
    success: bool,
    failure_reason: str,
    terminal_reason: str = "",
    durability_state: str = "staged",
    claim_state: str = "pending",
) -> dict:
    return _build_run_record_impl(
        url=url,
        item=item,
        success=success,
        failure_reason=failure_reason,
        terminal_reason=terminal_reason,
        durability_state=durability_state,
        claim_state=claim_state,
    )


def _load_persisted_run_records(execution_id: str) -> dict[str, dict]:
    return _load_persisted_run_records_impl(execution_id)


def _release_inflight_items_for_resume(execution_id: str) -> int:
    if not execution_id:
        return 0
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).release_inflight_items_for_resume(execution_id)


def _build_record_summary(records: dict[str, dict]) -> dict[str, int]:
    return _build_record_summary_impl(records)


def _is_finalized_run_record(record: dict[str, Any] | None) -> bool:
    if not isinstance(record, dict):
        return False
    claim_state = str(record.get("claim_state") or "").strip().lower()
    durability_state = str(record.get("durability_state") or "").strip().lower()
    return durability_state == "durable" or claim_state in {"committed", "acked", "failed"}


def _commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    _commit_items_file_impl(items_path, records)


async def _finalize_task_from_record(task: URLTask, record: dict) -> None:
    await _finalize_task_from_record_impl(task, record)


def _write_summary(path: Path, summary: dict) -> None:
    _write_summary_impl(path, summary)


def _persist_pipeline_run(context: PipelineFinalizationContext, records: dict[str, dict]) -> None:
    _persist_pipeline_run_impl(context, records)


def _promote_staged_output(staging_path: Path, final_path: Path) -> None:
    _promote_staged_output_impl(staging_path, final_path)


def _persist_run_snapshot(
    *,
    identity: TaskIdentity,
    fields: list[FieldDefinition],
    execution_id: str,
    thread_id: str,
    output_dir: str,
    pipeline_mode: PipelineMode,
    summary: dict[str, Any],
    collection_config: dict[str, Any] | None = None,
    extraction_config: dict[str, Any] | None = None,
    plan_knowledge: str = "",
    task_plan: dict[str, Any] | None = None,
    plan_journal: list[dict[str, Any]] | None = None,
    validation_failures: list[dict[str, Any]] | None = None,
    committed_records: list[dict[str, Any]] | None = None,
) -> None:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository, TaskRunPayload
    from ..common.storage.task_registry import normalize_url

    payload = TaskRunPayload(
        normalized_url=normalize_url(str(identity.list_url or "").strip()),
        original_url=str(identity.list_url or "").strip(),
        page_state_signature=str(identity.page_state_signature or "").strip(),
        anchor_url=str(identity.anchor_url or "").strip(),
        variant_label=str(identity.variant_label or "").strip(),
        task_description=str(identity.task_description or "").strip(),
        field_names=[str(field.name or "").strip() for field in fields if str(field.name or "").strip()],
        execution_id=execution_id,
        thread_id=thread_id,
        output_dir=output_dir,
        pipeline_mode=pipeline_mode.value,
        execution_state=str(summary.get("execution_state") or "running"),
        outcome_state=str(summary.get("outcome_state") or ""),
        promotion_state=str(summary.get("promotion_state") or ""),
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        failed_count=int(summary.get("failed_count", 0) or 0),
        validation_failure_count=int(summary.get("validation_failure_count", 0) or 0),
        success_rate=float(summary.get("success_rate", 0.0) or 0.0),
        error_message=str(summary.get("error") or ""),
        summary_json=dict(summary or {}),
        collection_config=dict(collection_config or {}),
        extraction_config=dict(extraction_config or {}),
        plan_knowledge=str(plan_knowledge or ""),
        task_plan=dict(task_plan or {}),
        plan_journal=list(plan_journal or []),
        validation_failures=list(validation_failures or []),
        committed_records=list(committed_records or []),
    )
    with session_scope() as session:
        TaskRepository(session).save_run(payload)


def _claim_persisted_item(*, execution_id: str, url: str, worker_id: str) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).claim_item(
            execution_id=execution_id,
            url=url,
            worker_id=worker_id,
            item_data={"url": url},
        )


def _commit_persisted_item(
    *,
    execution_id: str,
    url: str,
    item: dict[str, Any],
    worker_id: str,
) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).commit_item(
            execution_id=execution_id,
            url=url,
            item_data=item,
            worker_id=worker_id,
            terminal_reason="success",
        )


def _fail_persisted_item(
    *,
    execution_id: str,
    url: str,
    failure_reason: str,
    item: dict[str, Any],
    worker_id: str,
    terminal_reason: str,
    error_kind: str,
) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).fail_item(
            execution_id=execution_id,
            url=url,
            failure_reason=failure_reason,
            item_data=item,
            worker_id=worker_id,
            terminal_reason=terminal_reason,
            error_kind=error_kind,
        )


def _ack_persisted_item(*, execution_id: str, url: str) -> dict[str, Any]:
    from ..common.db.engine import session_scope
    from ..common.db.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).ack_item(execution_id=execution_id, url=url)


def _merge_extraction_configs(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged_fields: dict[str, dict[str, Any]] = {}
    ordered_names: list[str] = []

    def _consume(config: dict[str, Any]) -> None:
        for raw_field in list(dict(config or {}).get("fields") or []):
            if not isinstance(raw_field, dict):
                continue
            name = str(raw_field.get("name") or "").strip()
            if not name:
                continue
            if name not in ordered_names:
                ordered_names.append(name)
            normalized = dict(raw_field)
            normalized["xpath_fallbacks"] = [
                str(item).strip()
                for item in list(raw_field.get("xpath_fallbacks") or [])
                if str(item).strip()
            ]
            current = merged_fields.get(name)
            if current is None:
                merged_fields[name] = normalized
                continue

            current_xpath = str(current.get("xpath") or "").strip()
            incoming_xpath = str(normalized.get("xpath") or "").strip()
            current_validated = bool(current.get("xpath_validated"))
            incoming_validated = bool(normalized.get("xpath_validated"))
            if incoming_validated and (not current_validated or incoming_xpath):
                candidate = dict(normalized)
            elif incoming_xpath and not current_xpath:
                candidate = dict(normalized)
            else:
                candidate = dict(current)

            fallback_pool = [
                *list(current.get("xpath_fallbacks") or []),
                *list(normalized.get("xpath_fallbacks") or []),
            ]
            if current_xpath and current_xpath != str(candidate.get("xpath") or "").strip():
                fallback_pool.append(current_xpath)
            if incoming_xpath and incoming_xpath != str(candidate.get("xpath") or "").strip():
                fallback_pool.append(incoming_xpath)
            seen: set[str] = {str(candidate.get("xpath") or "").strip()} if str(candidate.get("xpath") or "").strip() else set()
            fallback_xpaths: list[str] = []
            for item in fallback_pool:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                fallback_xpaths.append(text)
            candidate["xpath_fallbacks"] = fallback_xpaths[:5]
            candidate["xpath_validated"] = current_validated or incoming_validated
            merged_fields[name] = candidate

    _consume(existing)
    _consume(incoming)
    return {"fields": [merged_fields[name] for name in ordered_names if name in merged_fields]}


def _set_state_error(state: dict[str, object], error: str) -> None:
    if not state.get("error"):
        state["error"] = error


def _record_extraction_evidence(
    state: dict[str, object] | None,
    *,
    url: str,
    extraction_config: dict[str, Any],
    success: bool,
) -> None:
    if state is None:
        return
    evidence = list(state.get("extraction_evidence") or [])
    evidence.append(
        {
            "url": url,
            "success": bool(success),
            "extraction_config": dict(extraction_config or {}),
        }
    )
    state["extraction_evidence"] = evidence
    state["extraction_config"] = _merge_extraction_configs(
        dict(state.get("extraction_config") or {}),
        dict(extraction_config or {}),
    )


def _resolve_run_redis_key_prefix(
    *,
    pipeline_mode: str | None,
    redis_key_prefix: str | None,
    execution_id: str,
) -> str | None:
    if redis_key_prefix:
        return redis_key_prefix
    mode = str(config.pipeline.mode if pipeline_mode is None else pipeline_mode).strip().lower()
    if mode != "redis":
        return None
    base_prefix = (config.redis.key_prefix or "autospider:urls").strip() or "autospider:urls"
    return f"{base_prefix}:run:{execution_id}"


async def run_pipeline(context: ExecutionContext) -> dict:
    request = context.request
    list_url = request.list_url
    task_description = request.task_description
    fields = list(context.fields)
    execution_brief = dict(request.execution_brief or {})
    output_dir = request.output_dir
    headless = request.headless
    explore_count = request.field_explore_count
    validate_count = request.field_validate_count
    max_pages = request.max_pages
    target_url_count = request.target_url_count
    guard_intervention_mode = request.guard_intervention_mode
    guard_thread_id = request.guard_thread_id
    selected_skills = list(context.selected_skills)
    plan_knowledge = context.plan_knowledge
    task_plan_snapshot = dict(context.task_plan_snapshot)
    plan_journal = list(context.plan_journal)
    initial_nav_steps = list(context.initial_nav_steps)
    anchor_url = context.identity.anchor_url or None
    page_state_signature = context.identity.page_state_signature
    variant_label = context.identity.variant_label or None
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    is_resume = context.resume_mode.value == "resume"
    resolved_execution_id = str(context.execution_id or "").strip()
    if not resolved_execution_id:
        resolved_execution_id = _build_execution_id(
            list_url=list_url,
            task_description=task_description,
            execution_brief=execution_brief,
            fields=fields,
            target_url_count=target_url_count,
            max_pages=max_pages,
            pipeline_mode=context.pipeline_mode.value,
            thread_id=guard_thread_id,
            page_state_signature=page_state_signature,
            anchor_url=anchor_url,
            variant_label=variant_label,
        )

    if explore_count is None:
        explore_count = config.field_extractor.explore_count
    if validate_count is None:
        validate_count = config.field_extractor.validate_count
    consumer_workers = int(context.consumer_concurrency or 1)
    effective_redis_key_prefix = _resolve_run_redis_key_prefix(
        pipeline_mode=context.pipeline_mode.value,
        redis_key_prefix=None,
        execution_id=resolved_execution_id,
    )

    channel, redis_manager = create_url_channel(
        mode=context.pipeline_mode.value,
        output_dir=output_dir,
        redis_key_prefix=effective_redis_key_prefix,
    )

    items_path = output_path / "pipeline_extracted_items.jsonl"
    summary_path = output_path / "pipeline_summary.json"
    staging_items_path = output_path / "pipeline_extracted_items.next.jsonl"
    staging_summary_path = output_path / "pipeline_summary.next.json"
    skill_runtime = SkillRuntime()

    _prepare_pipeline_output(
        output_path=output_path,
        items_path=staging_items_path,
        summary_path=staging_summary_path,
    )
    if is_resume:
        _release_inflight_items_for_resume(resolved_execution_id)
    run_records = _load_persisted_run_records(resolved_execution_id) if is_resume else {}

    summary = {
        "run_id": resolved_execution_id,
        "list_url": list_url,
        "anchor_url": str(anchor_url or ""),
        "page_state_signature": str(page_state_signature or ""),
        "variant_label": str(variant_label or ""),
        "task_description": task_description,
        "mode": context.pipeline_mode.value,
        "total_urls": 0,
        "success_count": 0,
        "failed_count": 0,
        "consumer_concurrency": consumer_workers,
        "target_url_count": target_url_count,
        "items_file": str(items_path),
        "summary_file": str(summary_path),
        "execution_id": resolved_execution_id,
        "durability_state": "staged",
        "durably_persisted": False,
        "terminal_reason": "",
    }

    sessions = PipelineSessionBundle(
        list_session=BrowserSession(
            headless=headless,
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=guard_thread_id,
            budget_key=resolved_execution_id,
            global_browser_budget=context.global_browser_budget,
        ),
    )
    await sessions.start()

    runtime_context = PipelineRuntimeContext(
        list_url=list_url,
        anchor_url=anchor_url,
        page_state_signature=page_state_signature,
        variant_label=variant_label,
        task_description=task_description,
        execution_brief=dict(execution_brief or {}),
        fields=fields,
        output_dir=output_dir,
        headless=headless,
        explore_count=explore_count,
        validate_count=validate_count,
        consumer_workers=consumer_workers,
        max_pages=max_pages,
        target_url_count=target_url_count,
        guard_intervention_mode=guard_intervention_mode,
        guard_thread_id=guard_thread_id,
        selected_skills=selected_skills,
        channel=channel,
        redis_manager=redis_manager,
        run_records=run_records,
        summary=summary,
        tracker=TaskProgressTracker(resolved_execution_id),
        skill_runtime=skill_runtime,
        sessions=sessions,
        plan_knowledge=plan_knowledge,
        task_plan_snapshot=dict(task_plan_snapshot or {}),
        plan_journal=list(plan_journal or []),
        initial_nav_steps=list(initial_nav_steps or []),
        url_only_mode=len(fields) == 0,
        execution_id=resolved_execution_id,
        resume_mode="resume" if is_resume else "fresh",
        global_browser_budget=context.global_browser_budget,
    )
    _persist_run_snapshot(
        identity=context.identity,
        fields=fields,
        execution_id=resolved_execution_id,
        thread_id=guard_thread_id,
        output_dir=output_dir,
        pipeline_mode=context.pipeline_mode,
        summary=summary,
        plan_knowledge=plan_knowledge,
        task_plan=task_plan_snapshot,
        plan_journal=plan_journal,
    )

    runtime_deps = PipelineRuntimeDependencies(
        browser_session_factory=BrowserSession,
        collector_cls=URLCollector,
        detail_page_worker_cls=DetailPageWorker,
        set_state_error=_set_state_error,
        process_task=_process_task,
    )
    services = create_pipeline_services(runtime_context, runtime_deps)

    finalizer = PipelineFinalizer(
        PipelineFinalizationDependencies(
            build_record_summary=_build_record_summary,
            classify_pipeline_result=_classify_pipeline_result,
            persist_pipeline_run=_persist_pipeline_run,
            commit_items_file=_commit_items_file,
            write_summary=_write_summary,
            promote_output=_promote_staged_output,
        )
    )

    try:
        await asyncio.gather(
            services.producer.run(),
            services.consumer_pool.run(),
        )
    finally:
        try:
            await finalizer.finalize(
                PipelineFinalizationContext(
                    list_url=list_url,
                    anchor_url=anchor_url,
                    page_state_signature=page_state_signature,
                    variant_label=variant_label,
                    task_description=task_description,
                    execution_brief=dict(execution_brief or {}),
                    fields=fields,
                    thread_id=guard_thread_id,
                    output_dir=output_dir,
                    output_path=output_path,
                    items_path=items_path,
                    summary_path=summary_path,
                    staging_items_path=staging_items_path,
                    staging_summary_path=staging_summary_path,
                    committed_records=_load_persisted_run_records(resolved_execution_id),
                    summary=summary,
                    state=runtime_context.state,
                    collection_config=dict(runtime_context.state.get("collection_config") or {}),
                    extraction_config=dict(runtime_context.state.get("extraction_config") or {}),
                    validation_failures=list(runtime_context.state.get("validation_failures") or []),
                    plan_knowledge=runtime_context.plan_knowledge,
                    task_plan=dict(runtime_context.task_plan_snapshot or {}),
                    plan_journal=list(runtime_context.plan_journal or []),
                    tracker=runtime_context.tracker,
                    sessions=sessions,
                )
            )
        finally:
            await channel.close()

    summary["collection_config"] = dict(runtime_context.state.get("collection_config") or {})
    summary["extraction_config"] = dict(runtime_context.state.get("extraction_config") or {})
    summary["extraction_evidence"] = list(runtime_context.state.get("extraction_evidence") or [])
    summary["validation_failures"] = list(runtime_context.state.get("validation_failures") or [])
    return summary


async def _process_task(
    extractor: DetailPageWorker,
    task: URLTask,
    run_records: dict[str, dict],
    summary_lock: asyncio.Lock,
    state: dict[str, object] | None = None,
    tracker: TaskProgressTracker | None = None,
    execution_id: str = "",
) -> None:
    url = (task.url or "").strip()
    if not url:
        await task.fail_task("empty_url")
        return

    worker_id = f"{execution_id}:{id(asyncio.current_task())}"
    async with summary_lock:
        existing_record = run_records.get(url)

    if _is_finalized_run_record(existing_record):
        if str(existing_record.get("claim_state") or "") == "claimed":
            await task.fail_task("duplicate_inflight_claim")
            return
        await _finalize_task_from_record(task, existing_record)
        if tracker:
            if existing_record.get("success") and existing_record.get("durability_state") == "durable":
                await tracker.record_success(url)
            elif not existing_record.get("success"):
                await tracker.record_failure(url, str(existing_record.get("failure_reason") or ""))
        return

    try:
        claimed_record = _claim_persisted_item(
            execution_id=execution_id,
            url=url,
            worker_id=worker_id,
        )
    except RuntimeError as exc:
        if str(exc) == "duplicate_inflight_claim":
            await task.fail_task("duplicate_inflight_claim")
            return
        raise

    async with summary_lock:
        run_records[url] = claimed_record

    try:
        worker_result = await extractor.extract(url)
        record = worker_result.record
    except BrowserInterventionRequired:
        async with summary_lock:
            run_records.pop(url, None)
        raise
    except Exception as exc:  # noqa: BLE001
        if state is not None:
            _set_state_error(state, f"extractor_system_error: {exc}")
            state["terminal_reason"] = "extractor_system_error"
        run_record = _fail_persisted_item(
            execution_id=execution_id,
            url=url,
            failure_reason=f"extractor_exception: {exc}",
            item={"url": url, "_error": f"extractor_exception: {exc}"},
            worker_id=worker_id,
            terminal_reason="extractor_system_error",
            error_kind="system_failure",
        )
    else:
        _record_extraction_evidence(
            state,
            url=url,
            extraction_config=dict(worker_result.extraction_config or {}),
            success=bool(record.success),
        )
        item = {"url": record.url}
        for field_result in record.fields:
                item[field_result.field_name] = field_result.value

        if record.success:
            run_record = _commit_persisted_item(
                execution_id=execution_id,
                url=url,
                item=item,
                worker_id=worker_id,
            )
        else:
            run_record = _fail_persisted_item(
                execution_id=execution_id,
                url=url,
                failure_reason=_build_error_reason(record),
                item=item,
                worker_id=worker_id,
                terminal_reason="field_extraction_failed",
                error_kind="business_failure",
            )

    async with summary_lock:
        run_records[url] = run_record

    if run_record.get("success"):
        await task.ack_task()
        run_record = _ack_persisted_item(execution_id=execution_id, url=url)
        async with summary_lock:
            run_records[url] = run_record
    else:
        await task.fail_task(str(run_record.get("failure_reason") or "extraction_failed"))

    if tracker:
        if run_record.get("success"):
            await tracker.record_success(url)
        elif not run_record.get("success"):
            await tracker.record_failure(url, run_record.get("failure_reason", ""))


def _build_error_reason(record) -> str:
    errors = []
    for field_result in record.fields:
        if field_result.error:
            errors.append(field_result.error)
    return "; ".join(errors) if errors else "extraction_failed"
