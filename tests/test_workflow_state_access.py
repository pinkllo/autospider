from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.graph.workflow_access import (
    coerce_workflow_state,
    current_plan,
    final_error,
    intent_fields,
)

FIELD_LIST = [
    {"name": "title", "description": "标题"},
    {"name": "published_at", "description": "发布时间"},
]


def test_coerce_workflow_state_maps_legacy_meta_and_intent_fields() -> None:
    legacy_state = {
        "thread_id": "thread-1",
        "conversation": {
            "clarified_task": {
                "fields": FIELD_LIST,
            }
        },
    }

    workflow = coerce_workflow_state(legacy_state)

    assert workflow["meta"]["thread_id"] == "thread-1"
    assert workflow["intent"]["fields"] == FIELD_LIST
    assert workflow["control"] == {}
    assert workflow["result"] == {}


def test_current_plan_reads_only_workflow_control_namespace() -> None:
    state = {
        "control": {"current_plan": {"steps": ["workflow-plan"]}},
        "planning": {"task_plan": {"steps": ["legacy-plan"]}},
        "task_plan": {"steps": ["legacy-root-plan"]},
    }

    assert current_plan(state) == {"steps": ["workflow-plan"]}


def test_intent_fields_reads_only_workflow_intent_namespace() -> None:
    state = {
        "intent": {"fields": FIELD_LIST},
        "conversation": {"clarified_task": {"fields": [{"name": "legacy"}]}},
    }

    assert intent_fields(state) == FIELD_LIST


def test_intent_fields_keeps_explicit_empty_workflow_namespace() -> None:
    state = {
        "intent": {"fields": []},
        "conversation": {"clarified_task": {"fields": FIELD_LIST}},
    }

    assert intent_fields(state) == []


def test_final_error_prefers_result_final_error() -> None:
    state = {
        "result": {
            "final_error": {"code": "RESULT", "message": "workflow error"},
            "error": {"code": "LEGACY_RESULT", "message": "legacy result error"},
        },
        "error": {"code": "ROOT", "message": "root error"},
    }

    assert final_error(state) == {"code": "RESULT", "message": "workflow error"}


def test_coerce_workflow_state_maps_root_summary_and_artifacts_into_result() -> None:
    legacy_state = {
        "summary": {"thread_id": "thread-1", "merged_items": 3},
        "artifacts": [{"label": "report", "path": "tmp/report.json"}],
    }

    workflow = coerce_workflow_state(legacy_state)

    assert workflow["result"] == {}


def test_coerce_workflow_state_preserves_real_legacy_field_list_shape() -> None:
    workflow = coerce_workflow_state(
        {
            "conversation": {
                "clarified_task": {
                    "fields": FIELD_LIST,
                }
            }
        }
    )

    assert workflow["intent"]["fields"] == FIELD_LIST
