from __future__ import annotations

import json

import pytest

from autospider.pipeline.runner import (
    _build_staged_record,
    _commit_items_file,
    _load_staged_records,
    _prepare_pipeline_workspace,
    _process_task,
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
