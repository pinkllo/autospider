from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.domain.planning import ExecutionBrief, SubTask, SubTaskMode
from autospider.pipeline.types import PipelineRunResult
from autospider.pipeline.worker import SubTaskWorker


@pytest.mark.asyncio
async def test_subtask_worker_execute_builds_execution_request_from_runtime_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.pipeline.runner as runner_module
    import autospider.pipeline.worker as worker_module

    captured: dict[str, object] = {}

    def fake_build_execution_context(request, *, fields=None):
        captured["request"] = request
        captured["fields"] = list(fields or [])
        return SimpleNamespace(
            pipeline_mode=SimpleNamespace(value="memory"),
            execution_id="exec-1",
        )

    async def fake_run_pipeline(_context):
        return PipelineRunResult.from_raw(
            {
                "total_urls": 1,
                "success_count": 1,
                "failed_count": 0,
                "outcome_state": "success",
                "execution_id": "exec-1",
                "items_file": "",
                "summary_file": "",
            }
        )

    monkeypatch.setattr(worker_module, "build_execution_context", fake_build_execution_context)
    monkeypatch.setattr(runner_module, "run_pipeline", fake_run_pipeline)

    subtask = SubTask(
        id="leaf_001",
        name="采购公告",
        list_url="https://example.com/notices/purchase",
        anchor_url="https://example.com/notices",
        page_state_signature="sig-purchase",
        variant_label="purchase",
        task_description="采集采购公告详情页",
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="收集采购公告详情页链接"),
        plan_node_id="node_002",
    )
    worker = SubTaskWorker(
        subtask=subtask,
        fields=[{"name": "title", "description": "公告标题", "required": True}],
        output_dir="output",
        thread_id="thread-1",
        plan_knowledge="structured planning knowledge",
        task_plan_snapshot={"plan_id": "plan_001"},
        plan_journal=[{"entry_id": "journal_001"}],
    )
    worker.decision_context = {"page_model": {"page_type": "legacy"}}
    worker.world_snapshot = {
        "request_params": {"list_url": "https://example.com/notices", "target_url_count": 8},
        "world_model": {
            "request_params": {"list_url": "https://example.com/notices", "target_url_count": 8},
            "page_models": {
                "node_002": {
                    "page_id": "node_002",
                    "page_type": "list_page",
                    "metadata": {"observations": "采购公告列表页"},
                }
            },
            "failure_records": [
                {
                    "page_id": "node_002",
                    "category": "navigation",
                    "detail": "snapshot-timeout",
                }
            ],
            "success_criteria": {"target_url_count": 8},
        },
        "failure_records": [
            {
                "page_id": "node_002",
                "category": "navigation",
                "detail": "snapshot-timeout",
            }
        ],
    }
    worker.control_snapshot = {
        "current_plan": {"goal": "采集采购公告详情页", "page_id": "node_001", "stage": "planning_seeded"},
        "dispatch_policy": {"strategy": "parallel", "max_concurrency": 2},
        "recovery_policy": {"max_retries": 2, "fail_fast": True},
    }
    worker.failure_records = [
        {
            "page_id": "node_002",
            "category": "navigation",
            "detail": "runtime-dom-changed",
        }
    ]

    await worker.execute()

    request = captured["request"]
    assert request.plan_knowledge == "structured planning knowledge"
    assert request.world_snapshot == worker.world_snapshot
    assert request.failure_records == worker.failure_records
    assert request.decision_context["page_model"]["page_type"] == "list_page"
    assert request.decision_context["page_model"]["metadata"]["observations"] == "采购公告列表页"
    assert request.decision_context["recent_failures"] == [
        {
            "page_id": "node_002",
            "category": "navigation",
            "detail": "runtime-dom-changed",
            "metadata": {},
        }
    ]
