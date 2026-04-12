from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.workflow_access import (
    coerce_workflow_state,
    current_plan,
    final_error,
    intent_fields,
)


def test_coerce_workflow_state_maps_legacy_fields_into_workflow_namespaces() -> None:
    legacy_state = {
        "thread_id": "thread-1",
        "conversation": {
            "clarified_task": {
                "fields": {"region": "hk", "keywords": ["tea"]},
            }
        },
        "planning": {"task_plan": {"steps": ["collect"]}},
        "result": {"summary": {"items": 2}},
    }

    workflow = coerce_workflow_state(legacy_state)

    assert workflow["meta"]["thread_id"] == "thread-1"
    assert workflow["intent"]["fields"] == {"region": "hk", "keywords": ["tea"]}
    assert workflow["control"]["current_plan"] == {"steps": ["collect"]}
    assert workflow["result"]["summary"] == {"items": 2}


def test_current_plan_reads_only_workflow_control_namespace() -> None:
    state = {
        "control": {"current_plan": {"steps": ["workflow-plan"]}},
        "planning": {"task_plan": {"steps": ["legacy-plan"]}},
        "task_plan": {"steps": ["legacy-root-plan"]},
    }

    assert current_plan(state) == {"steps": ["workflow-plan"]}


def test_intent_fields_reads_only_workflow_intent_namespace() -> None:
    state = {
        "intent": {"fields": {"region": "workflow"}},
        "conversation": {"clarified_task": {"fields": {"region": "legacy"}}},
    }

    assert intent_fields(state) == {"region": "workflow"}


def test_final_error_prefers_result_final_error() -> None:
    state = {
        "result": {
            "final_error": {"code": "RESULT", "message": "workflow error"},
            "error": {"code": "LEGACY_RESULT", "message": "legacy result error"},
        },
        "error": {"code": "ROOT", "message": "root error"},
    }

    assert final_error(state) == {"code": "RESULT", "message": "workflow error"}
