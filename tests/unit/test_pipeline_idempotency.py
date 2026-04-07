from __future__ import annotations

import json

import pytest

from autospider.common.experience.skill_sedimenter import SkillPromotionContext
from autospider.common.channel.base import URLTask
from autospider.common.config import config
from autospider.domain.fields import FieldDefinition
from autospider.field.models import FieldExtractionResult, PageExtractionRecord
from autospider.pipeline import runner as pipeline_runner
from autospider.pipeline.runner import (
    _classify_pipeline_result,
    _build_run_record,
    _build_record_summary,
    _commit_items_file,
    _load_persisted_run_records,
    _prepare_pipeline_output,
    _process_task,
    _should_promote_skill,
    _strip_draft_markers_from_skill_content,
    _try_sediment_skill,
)


class _DummyTask:
    def __init__(self, url: str):
        self.url = url
        self.acked = 0
        self.failed: list[str] = []

    async def ack_task(self) -> None:
        self.acked += 1

    async def fail_task(self, reason: str) -> None:
        self.failed.append(reason)


class _UnusedExtractor:
    def __init__(self):
        self.called = False

    async def extract(self, url: str):
        self.called = True
        raise AssertionError(f"extractor should not run for {url}")


class _FakePage:
    async def goto(self, *args, **kwargs):
        return None


class _FakeBrowserSession:
    def __init__(self, *args, **kwargs):
        self.page = _FakePage()

    async def start(self):
        return None

    async def stop(self):
        return None


class _NoopTracker:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id

    async def set_total(self, total: int):
        return None

    async def record_success(self, url: str = ""):
        return None

    async def record_failure(self, url: str = "", error: str = ""):
        return None

    async def mark_done(self, final_status: str = "completed"):
        return None


class _ExplodingChannel:
    async def close(self):
        return None

    async def fetch(self, *args, **kwargs):
        raise RuntimeError("stop consumer")


class _QueueBackedChannel:
    def __init__(self):
        self.pending: list[str] = []
        self.closed = False
        self.close_calls = 0

    async def publish(self, url: str):
        if self.closed:
            raise RuntimeError("channel already closed")
        self.pending.append(url)

    async def fetch(self, max_items: int, timeout_s: float | None):
        if self.closed:
            return []
        batch = self.pending[:max_items]
        self.pending = self.pending[max_items:]
        return [URLTask(url=url, ack=self._ack, fail=self._fail) for url in batch]

    async def close(self):
        self.close_calls += 1
        self.closed = True
        self.pending.clear()

    async def _ack(self):
        return None

    async def _fail(self, reason: str):
        return None


def test_strip_draft_markers_from_skill_content_for_promoted_skills():
    content = (
        "---\n"
        "name: ygp.gdzwfw.gov.cn 站点采集\n"
        "description: ygp.gdzwfw.gov.cn 数据采集技能（草稿）。DFS 发现阶段生成，待 Worker 执行后补充字段提取规则。\n"
        "---\n\n"
        "# ygp.gdzwfw.gov.cn 采集指南（草稿）\n\n"
        "## 基本信息\n\n"
        "- **状态**: 📝 draft\n"
    )

    cleaned = _strip_draft_markers_from_skill_content(content)

    assert "（草稿）" not in cleaned
    assert "📝 draft" not in cleaned
    assert "# ygp.gdzwfw.gov.cn 采集指南" in cleaned
    assert "description: ygp.gdzwfw.gov.cn 数据采集技能。" in cleaned


def test_should_promote_skill_requires_clean_success():
    assert _should_promote_skill(
        state={},
        summary={"success_count": 3, "total_urls": 4},
        validation_failures=[],
    )
    assert _should_promote_skill(
        state={},
        summary={"success_count": 3, "total_urls": 3},
        validation_failures=[],
    )
    assert not _should_promote_skill(
        state={"error": "boom"},
        summary={"success_count": 3, "total_urls": 3},
        validation_failures=[],
    )
    assert not _should_promote_skill(
        state={},
        summary={"success_count": 7, "total_urls": 10},
        validation_failures=[],
    )
    assert not _should_promote_skill(
        state={},
        summary={"success_count": 3, "total_urls": 3},
        validation_failures=[{"url": "https://example.com/1"}],
    )


def test_classify_pipeline_result_uses_quality_threshold_and_validation_barrier():
    reusable = _classify_pipeline_result(
        total_urls=4,
        success_count=3,
        state_error=None,
        validation_failures=[],
    )
    assert reusable["outcome_state"] == "success"
    assert reusable["promotion_state"] == "reusable"
    assert reusable["success_rate"] == 0.75

    diagnostic = _classify_pipeline_result(
        total_urls=10,
        success_count=8,
        state_error=None,
        validation_failures=[{"url": "https://example.com/1"}],
    )
    assert diagnostic["outcome_state"] == "partial_success"
    assert diagnostic["promotion_state"] == "diagnostic_only"
    assert diagnostic["validation_failure_count"] == 1


def test_prepare_pipeline_output_resets_export_files(tmp_path):
    items_path = tmp_path / "pipeline_extracted_items.jsonl"
    summary_path = tmp_path / "pipeline_summary.json"
    items_path.write_text('{"url": "https://example.com/a"}\n', encoding="utf-8")
    summary_path.write_text('{"total_urls": 1}\n', encoding="utf-8")

    _prepare_pipeline_output(
        output_path=tmp_path,
        items_path=items_path,
        summary_path=summary_path,
    )

    assert not items_path.exists()
    assert not summary_path.exists()


def test_commit_items_file_writes_single_visible_snapshot(tmp_path):
    records = {
        "https://example.com/b": _build_run_record(
            url="https://example.com/b",
            item={"url": "https://example.com/b", "title": "B"},
            success=True,
            failure_reason="",
        ),
        "https://example.com/a": _build_run_record(
            url="https://example.com/a",
            item={"url": "https://example.com/a", "title": "A"},
            success=False,
            failure_reason="failed",
        ),
    }

    items_path = tmp_path / "pipeline_extracted_items.jsonl"
    _commit_items_file(items_path, records)

    lines = items_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["url"] == "https://example.com/a"
    assert json.loads(lines[1])["url"] == "https://example.com/b"


def test_build_run_record_defaults_to_runtime_not_durable():
    record = _build_run_record(
        url="https://example.com/a",
        item={"url": "https://example.com/a"},
        success=True,
        failure_reason="",
    )

    assert record["durably_persisted"] is False
    assert record["record_source"] == "runtime"


@pytest.mark.asyncio
async def test_process_task_reuses_persisted_record_without_reextract():
    task = _DummyTask("https://example.com/a")
    extractor = _UnusedExtractor()
    run_records = {
        "https://example.com/a": {
            **_build_run_record(
                url="https://example.com/a",
                item={"url": "https://example.com/a", "title": "A"},
                success=True,
                failure_reason="",
            ),
            "durably_persisted": True,
            "record_source": "db",
        }
    }

    import asyncio

    await _process_task(
        extractor=extractor,
        task=task,
        run_records=run_records,
        summary_lock=asyncio.Lock(),
    )

    assert extractor.called is False
    assert task.acked == 1
    assert task.failed == []




@pytest.mark.asyncio
async def test_finalize_task_from_runtime_success_requeues_until_persisted():
    task = _DummyTask("https://example.com/a")
    record = _build_run_record(
        url="https://example.com/a",
        item={"url": "https://example.com/a"},
        success=True,
        failure_reason="",
    )

    await pipeline_runner._finalize_task_from_record(task, record)

    assert task.acked == 0
    assert task.failed == ["result_not_persisted"]


def test_build_record_summary_counts_success_and_failure():
    records = {
        "https://example.com/a": _build_run_record(
            url="https://example.com/a",
            item={"url": "https://example.com/a"},
            success=True,
            failure_reason="",
        ),
        "https://example.com/b": _build_run_record(
            url="https://example.com/b",
            item={"url": "https://example.com/b"},
            success=False,
            failure_reason="boom",
        ),
    }

    summary = _build_record_summary(records)

    assert summary == {"total_urls": 2, "success_count": 1}


@pytest.mark.asyncio
async def test_run_pipeline_passes_max_pages_without_mutating_global_config(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    original_max_pages = config.url_collector.max_pages

    class _FakeCollector:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self):
            return type(
                "_Result",
                (),
                {
                    "collected_urls": [],
                    "plan_upgrade_requested": False,
                    "plan_upgrade_reason": "",
                    "plan_upgrade_site_url": "",
                },
            )()

    monkeypatch.setattr(pipeline_runner, "BrowserSession", _FakeBrowserSession)
    monkeypatch.setattr(pipeline_runner, "URLCollector", _FakeCollector)
    monkeypatch.setattr(pipeline_runner, "create_url_channel", lambda **kwargs: (_ExplodingChannel(), None))
    monkeypatch.setattr(pipeline_runner, "_load_persisted_run_records", lambda execution_id: {})
    monkeypatch.setattr(pipeline_runner, "_write_summary", lambda summary_path, summary: None)
    monkeypatch.setattr(pipeline_runner, "_try_sediment_skill", lambda **kwargs: None)

    with pytest.raises(RuntimeError, match="stop consumer"):
        await pipeline_runner.run_pipeline(
            list_url="https://example.com/list",
            task_description="采集公告",
            fields=[],
            output_dir=str(tmp_path),
            max_pages=11,
            target_url_count=3,
        )

    assert captured["max_pages"] == 11
    assert config.url_collector.max_pages == original_max_pages


@pytest.mark.asyncio
async def test_run_pipeline_keeps_channel_open_until_consumer_drains_remaining_urls(monkeypatch, tmp_path):
    channel = _QueueBackedChannel()

    class _PublishingCollector:
        def __init__(self, **kwargs):
            self.url_channel = kwargs["url_channel"]

        async def run(self):
            urls = [f"https://example.com/detail/{idx}" for idx in range(10)]
            for url in urls:
                await self.url_channel.publish(url)
            return type(
                "_Result",
                (),
                {
                    "collected_urls": urls,
                    "plan_upgrade_requested": False,
                    "plan_upgrade_reason": "",
                    "plan_upgrade_site_url": "",
                },
            )()

    class _FakeDetailPageWorker:
        def __init__(self, *args, **kwargs):
            self.fields = kwargs["fields"]

        async def extract(self, url: str):
            record = PageExtractionRecord(
                url=url,
                fields=[
                    FieldExtractionResult(
                        field_name="project_name",
                        value=f"value:{url.rsplit('/', 1)[-1]}",
                    )
                ],
                success=True,
            )
            return type(
                "_Result",
                (),
                {
                    "record": record,
                    "extraction_config": {
                        "fields": [
                            {
                                "name": "project_name",
                                "description": "项目名称",
                                "xpath": '//*[@id="title"]',
                                "required": True,
                                "data_type": "text",
                                "extraction_source": None,
                                "fixed_value": None,
                            }
                        ]
                    },
                },
            )()

    monkeypatch.setattr(pipeline_runner, "BrowserSession", _FakeBrowserSession)
    monkeypatch.setattr(pipeline_runner, "URLCollector", _PublishingCollector)
    monkeypatch.setattr(
        pipeline_runner,
        "create_url_channel",
        lambda **kwargs: (channel, None),
    )
    monkeypatch.setattr(pipeline_runner, "DetailPageWorker", _FakeDetailPageWorker)
    monkeypatch.setattr(pipeline_runner, "TaskProgressTracker", _NoopTracker)
    monkeypatch.setattr(pipeline_runner, "_load_persisted_run_records", lambda execution_id: {})
    monkeypatch.setattr(pipeline_runner, "_try_sediment_skill", lambda **kwargs: None)

    result = await pipeline_runner.run_pipeline(
        list_url="https://example.com/list",
        task_description="采集项目名称",
        fields=[FieldDefinition(name="project_name", description="项目名称")],
        output_dir=str(tmp_path),
        explore_count=3,
        validate_count=4,
        consumer_concurrency=1,
        target_url_count=10,
    )

    assert result["total_urls"] == 10
    assert result["success_count"] == 10
    assert channel.close_calls == 1


def test_load_persisted_run_records_returns_empty_for_blank_execution_id():
    assert _load_persisted_run_records("") == {}


def test_try_sediment_skill_skips_low_quality_run(tmp_path):
    result = _should_promote_skill(
        state={},
        summary={"success_count": 2, "total_urls": 2, "promotion_state": "diagnostic_only"},
        validation_failures=[{"url": "https://example.com/detail/1"}],
    )

    assert result is False


def test_pipeline_finalizer_passes_context_and_evidence_to_sedimentation(tmp_path):
    captured: dict[str, object] = {}

    def _fake_try_sediment_skill(**kwargs):
        captured.update(kwargs)
        return None

    finalizer = pipeline_runner.PipelineFinalizer(
        pipeline_runner.PipelineFinalizationDependencies(
            build_record_summary=lambda records: {"total_urls": 1, "success_count": 1},
            classify_pipeline_result=lambda **kwargs: {
                "outcome_state": "success",
                "promotion_state": "reusable",
                "success_rate": 1.0,
                "validation_failure_count": 0,
                "execution_state": "completed",
            },
            persist_pipeline_run=lambda context, records: None,
            commit_items_file=lambda items_path, records: None,
            write_summary=lambda summary_path, summary: None,
            try_sediment_skill=_fake_try_sediment_skill,
            cleanup_output_draft_skill=lambda list_url, output_dir: None,
        )
    )

    class _Field:
        def model_dump(self):
            return {"name": "title", "description": "标题"}

    class _Sessions:
        def __init__(self):
            self.stopped = False

        async def stop(self):
            self.stopped = True

    sessions = _Sessions()
    tracker = _NoopTracker("run-1")

    context = pipeline_runner.PipelineFinalizationContext(
        list_url="https://example.com/list",
        anchor_url="https://example.com/category",
        page_state_signature="state-a",
        variant_label="招标公告",
        task_description="采集标题",
        execution_brief={},
        fields=[_Field()],
        thread_id="",
        output_dir=str(tmp_path),
        output_path=tmp_path,
        items_path=tmp_path / "items.jsonl",
        summary_path=tmp_path / "summary.json",
        committed_records={
            "https://example.com/detail/1": _build_run_record(
                url="https://example.com/detail/1",
                item={"url": "https://example.com/detail/1", "title": "A"},
                success=True,
                failure_reason="",
            )
        },
        summary={},
        state={
            "collection_config": {},
            "extraction_config": {},
            "validation_failures": [],
            "extraction_evidence": [
                {
                    "url": "https://example.com/detail/1",
                    "success": True,
                    "extraction_config": {
                        "fields": [{"name": "title", "xpath": "//h1", "xpath_validated": True}]
                    },
                }
            ],
        },
        collection_config={},
        extraction_config={},
        validation_failures=[],
        plan_knowledge="",
        task_plan={},
        plan_journal=[],
        promote_skill=True,
        promotion_context={"category_name": "招标公告"},
        tracker=tracker,
        sessions=sessions,
    )

    import asyncio
    asyncio.run(finalizer.finalize(context))

    payload = captured["payload"]
    assert payload.extraction_evidence[0]["url"] == "https://example.com/detail/1"
    assert payload.promotion_context == SkillPromotionContext(
        anchor_url="https://example.com/category",
        page_state_signature="state-a",
        variant_label="招标公告",
        context={"category_name": "招标公告"},
    )
    assert sessions.stopped is True

