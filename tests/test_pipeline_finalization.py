from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autospider.pipeline import finalization


class _TrackerStub:
    def __init__(self) -> None:
        self.done_calls: list[str] = []

    async def mark_done(self, status: str) -> None:
        self.done_calls.append(status)


class _SessionsStub:
    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1


async def test_finalize_marks_empty_committed_records_as_not_durable(monkeypatch) -> None:
    tracker = _TrackerStub()
    sessions = _SessionsStub()
    summary = {"terminal_reason": ""}
    output_root = Path("artifacts") / "test_tmp" / "pipeline-finalization"
    runtime_state = SimpleNamespace(
        error=None,
        terminal_reason="",
        validation_failures=[],
        collection_config={},
        extraction_config={},
        extraction_evidence=[],
    )
    deps = finalization.PipelineFinalizationDependencies(
        build_record_summary=finalization.build_record_summary,
        classify_pipeline_result=finalization.classify_pipeline_result,
        persist_pipeline_records=lambda context, records: None,
        commit_items_file=lambda items_path, records: None,
        write_summary=lambda path, payload: None,
        promote_output=lambda staging_path, final_path: None,
    )
    context = finalization.PipelineFinalizationContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect records",
        execution_brief={},
        fields=[],
        thread_id="thread-1",
        output_dir=str(output_root),
        output_path=output_root,
        items_path=output_root / "items.jsonl",
        summary_path=output_root / "summary.json",
        staging_items_path=output_root / "items.staging.jsonl",
        staging_summary_path=output_root / "summary.staging.json",
        committed_records={},
        summary=summary,
        runtime_state=runtime_state,
        plan_knowledge="",
        task_plan={},
        plan_journal=[],
        tracker=tracker,
        sessions=sessions,
    )

    monkeypatch.setattr(finalization, "promote_pipeline_skill", lambda context: None)

    await finalization.PipelineFinalizer(deps).finalize(context)

    assert summary["durability_state"] == finalization.DURABILITY_STATE_STAGED
    assert summary["durably_persisted"] is False
    assert tracker.done_calls == [finalization.EXECUTION_STATE_COMPLETED]


def test_classify_browser_intervention_as_interrupted() -> None:
    result = finalization.classify_pipeline_result(
        total_urls=1,
        success_count=0,
        state_error=None,
        validation_failures=[],
        terminal_reason="browser_intervention",
    )

    assert result["execution_state"] == finalization.EXECUTION_STATE_INTERRUPTED
    assert result["outcome_state"] == "interrupted"
    assert result["promotion_state"] == "rejected"


async def test_finalize_marks_interrupted_when_terminal_reason_is_browser_intervention(monkeypatch) -> None:
    tracker = _TrackerStub()
    sessions = _SessionsStub()
    summary = {"terminal_reason": ""}
    output_root = Path("artifacts") / "test_tmp" / "pipeline-finalization-interrupted"
    runtime_state = SimpleNamespace(
        error=None,
        terminal_reason="browser_intervention",
        validation_failures=[],
        collection_config={},
        extraction_config={},
        extraction_evidence=[],
    )
    deps = finalization.PipelineFinalizationDependencies(
        build_record_summary=finalization.build_record_summary,
        classify_pipeline_result=finalization.classify_pipeline_result,
        persist_pipeline_records=lambda context, records: None,
        commit_items_file=lambda items_path, records: None,
        write_summary=lambda path, payload: None,
        promote_output=lambda staging_path, final_path: None,
    )
    context = finalization.PipelineFinalizationContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect records",
        execution_brief={},
        fields=[],
        thread_id="thread-1",
        output_dir=str(output_root),
        output_path=output_root,
        items_path=output_root / "items.jsonl",
        summary_path=output_root / "summary.json",
        staging_items_path=output_root / "items.staging.jsonl",
        staging_summary_path=output_root / "summary.staging.json",
        committed_records={},
        summary=summary,
        runtime_state=runtime_state,
        plan_knowledge="",
        task_plan={},
        plan_journal=[],
        tracker=tracker,
        sessions=sessions,
    )

    monkeypatch.setattr(finalization, "promote_pipeline_skill", lambda context: None)

    await finalization.PipelineFinalizer(deps).finalize(context)

    assert tracker.done_calls == [finalization.EXECUTION_STATE_INTERRUPTED]


async def test_finalize_reclassifies_and_rewrites_summary_when_export_fails(
    monkeypatch,
) -> None:
    tracker = _TrackerStub()
    sessions = _SessionsStub()
    summary = {"terminal_reason": "", "execution_id": "run-1"}
    runtime_state = SimpleNamespace(
        error=None,
        terminal_reason="",
        validation_failures=[],
        collection_config={},
        extraction_config={},
        extraction_evidence=[],
    )
    written_summaries: list[tuple[Path, dict]] = []
    committed_records = {
        "https://example.com/item-1": finalization.build_run_record(
            url="https://example.com/item-1",
            item={"url": "https://example.com/item-1"},
            success=True,
            failure_reason="",
            durability_state=finalization.DURABILITY_STATE_DURABLE,
            claim_state="acked",
        )
    }
    output_root = Path("artifacts") / "test_tmp" / "pipeline-finalization-export-failure"

    class _UnexpectedSkillSedimenter:
        def sediment_from_pipeline_result(self, payload) -> None:  # noqa: ANN001
            raise AssertionError(f"skill promotion should not run after export failure: {payload}")

    def write_summary(path: Path, payload: dict) -> None:
        written_summaries.append((path, dict(payload)))

    def promote_output(staging_path: Path, final_path: Path) -> None:
        raise OSError(f"failed to promote {staging_path.name} -> {final_path.name}")

    deps = finalization.PipelineFinalizationDependencies(
        build_record_summary=finalization.build_record_summary,
        classify_pipeline_result=finalization.classify_pipeline_result,
        persist_pipeline_records=lambda context, records: None,
        commit_items_file=lambda items_path, records: None,
        write_summary=write_summary,
        promote_output=promote_output,
    )
    context = finalization.PipelineFinalizationContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect records",
        execution_brief={},
        fields=[],
        thread_id="thread-1",
        output_dir=str(output_root),
        output_path=output_root,
        items_path=output_root / "items.jsonl",
        summary_path=output_root / "summary.json",
        staging_items_path=output_root / "items.staging.jsonl",
        staging_summary_path=output_root / "summary.staging.json",
        committed_records=committed_records,
        summary=summary,
        runtime_state=runtime_state,
        plan_knowledge="",
        task_plan={},
        plan_journal=[],
        tracker=tracker,
        sessions=sessions,
    )

    monkeypatch.setattr(finalization, "SkillSedimenter", _UnexpectedSkillSedimenter)

    await finalization.PipelineFinalizer(deps).finalize(context)

    assert summary["error"] == "failed to promote items.staging.jsonl -> items.jsonl"
    assert summary["export_state"] == "failed"
    assert summary["terminal_reason"] == "export_failed"
    assert summary["execution_state"] == finalization.EXECUTION_STATE_FAILED
    assert summary["outcome_state"] == finalization.OUTCOME_STATE_SYSTEM_FAILURE
    assert summary["promotion_state"] == "diagnostic_only"
    assert summary["durability_state"] == finalization.DURABILITY_STATE_DURABLE
    assert summary["durably_persisted"] is True
    assert tracker.done_calls == [finalization.EXECUTION_STATE_FAILED]
    assert written_summaries == [
        (
            context.staging_summary_path,
            {
                "terminal_reason": "",
                "execution_id": "run-1",
                "total_urls": 1,
                "success_count": 1,
                "failed_count": 0,
                "durability_state": finalization.DURABILITY_STATE_DURABLE,
                "durably_persisted": True,
                "execution_state": finalization.EXECUTION_STATE_COMPLETED,
                "outcome_state": finalization.OUTCOME_STATE_SUCCESS,
                "promotion_state": "reusable",
                "success_rate": 1.0,
                "required_field_success_rate": 1.0,
                "validation_failure_count": 0,
            },
        ),
        (
            context.summary_path,
            {
                "terminal_reason": "export_failed",
                "execution_id": "run-1",
                "total_urls": 1,
                "success_count": 1,
                "failed_count": 0,
                "durability_state": finalization.DURABILITY_STATE_DURABLE,
                "durably_persisted": True,
                "execution_state": finalization.EXECUTION_STATE_FAILED,
                "outcome_state": finalization.OUTCOME_STATE_SYSTEM_FAILURE,
                "promotion_state": "diagnostic_only",
                "success_rate": 1.0,
                "required_field_success_rate": 1.0,
                "validation_failure_count": 0,
                "error": "failed to promote items.staging.jsonl -> items.jsonl",
                "export_state": "failed",
            },
        ),
    ]
