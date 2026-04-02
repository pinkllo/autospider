from __future__ import annotations

import json

import pytest

from autospider.common.config import config
from autospider.domain.fields import FieldDefinition
from autospider.pipeline import runner as pipeline_runner
from autospider.pipeline.runner import (
    _build_staged_record,
    _commit_items_file,
    _load_staged_records,
    _prepare_pipeline_workspace,
    _process_task,
    _should_promote_skill,
    _strip_draft_markers_from_skill_content,
    _try_sediment_skill,
    _write_staged_record,
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

    async def _extract_from_url(self, url: str):
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


class _ExplodingChannel:
    async def close(self):
        return None

    async def get_task(self):
        raise RuntimeError("stop consumer")


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
        summary={"success_count": 2, "total_urls": 3},
        validation_failures=[],
    )
    assert not _should_promote_skill(
        state={},
        summary={"success_count": 3, "total_urls": 3},
        validation_failures=[{"url": "https://example.com/1"}],
    )


def test_prepare_pipeline_workspace_resets_stale_attempt_outputs(tmp_path):
    staging_dir = tmp_path / ".pipeline_items"
    items_path = tmp_path / "pipeline_extracted_items.jsonl"
    summary_path = tmp_path / "pipeline_summary.json"
    manifest_path = tmp_path / "pipeline_execution.json"

    _prepare_pipeline_workspace(
        output_path=tmp_path,
        staging_dir=staging_dir,
        items_path=items_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        execution_id="old-exec",
        list_url="https://example.com/list",
        task_description="old",
    )
    _write_staged_record(
        staging_dir,
        _build_staged_record(
            url="https://example.com/a",
            item={"url": "https://example.com/a", "title": "A"},
            success=True,
            failure_reason="",
        ),
    )
    items_path.write_text('{"url": "https://example.com/a"}\n', encoding="utf-8")
    summary_path.write_text('{"total_urls": 1}\n', encoding="utf-8")

    _prepare_pipeline_workspace(
        output_path=tmp_path,
        staging_dir=staging_dir,
        items_path=items_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        execution_id="new-exec",
        list_url="https://example.com/list",
        task_description="new",
    )

    assert _load_staged_records(staging_dir) == {}
    assert not items_path.exists()
    assert not summary_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["execution_id"] == "new-exec"


def test_commit_items_file_writes_single_visible_snapshot(tmp_path):
    staging_dir = tmp_path / ".pipeline_items"
    staging_dir.mkdir(parents=True, exist_ok=True)
    _write_staged_record(
        staging_dir,
        _build_staged_record(
            url="https://example.com/b",
            item={"url": "https://example.com/b", "title": "B"},
            success=True,
            failure_reason="",
        ),
    )
    _write_staged_record(
        staging_dir,
        _build_staged_record(
            url="https://example.com/a",
            item={"url": "https://example.com/a", "title": "A"},
            success=False,
            failure_reason="failed",
        ),
    )

    items_path = tmp_path / "pipeline_extracted_items.jsonl"
    records = _load_staged_records(staging_dir)
    _commit_items_file(items_path, records)

    lines = items_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["url"] == "https://example.com/a"
    assert json.loads(lines[1])["url"] == "https://example.com/b"


@pytest.mark.asyncio
async def test_process_task_reuses_staged_record_without_reextract(tmp_path):
    staging_dir = tmp_path / ".pipeline_items"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_record = _build_staged_record(
        url="https://example.com/a",
        item={"url": "https://example.com/a", "title": "A"},
        success=True,
        failure_reason="",
    )
    _write_staged_record(staging_dir, staged_record)
    staged_records = _load_staged_records(staging_dir)

    task = _DummyTask("https://example.com/a")
    extractor = _UnusedExtractor()

    import asyncio

    await _process_task(
        extractor=extractor,
        task=task,
        staging_dir=staging_dir,
        staged_records=staged_records,
        summary_lock=asyncio.Lock(),
    )

    assert extractor.called is False
    assert task.acked == 1
    assert task.failed == []


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
    monkeypatch.setattr(pipeline_runner, "_load_staged_records", lambda staging_dir: {})
    monkeypatch.setattr(pipeline_runner, "_commit_items_file", lambda items_path, records: None)
    monkeypatch.setattr(pipeline_runner, "_write_summary", lambda summary_path, summary: None)

    result = await pipeline_runner.run_pipeline(
        list_url="https://example.com/list",
        task_description="采集公告",
        fields=[],
        output_dir=str(tmp_path),
        max_pages=11,
        target_url_count=3,
    )

    assert captured["max_pages"] == 11
    assert config.url_collector.max_pages == original_max_pages
    assert result["total_urls"] == 0
    assert result["success_count"] == 0
    assert "started_at" not in result
    assert "finished_at" not in result


def test_try_sediment_skill_skips_low_quality_run(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "extraction_result.json").write_text(
        json.dumps({"validation_failures": [{"url": "https://example.com/detail/1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _try_sediment_skill(
        list_url="https://example.com/list",
        task_description="采集公告",
        fields=[FieldDefinition(name="title", description="标题")],
        state={},
        summary={"success_count": 2, "total_urls": 2},
        output_dir=str(output_dir),
    )

    assert result is None

