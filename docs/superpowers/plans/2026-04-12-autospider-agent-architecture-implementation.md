# AutoSpider Agent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first complete implementation of AutoSpider's domain-shaped workflow state, shared world model, recovery control loop, and learning persistence without replacing the existing LangGraph + pipeline runtime.

**Architecture:** The rollout lands in seven shippable milestones. We first introduce new state and contract modules behind explicit compatibility adapters, then wire planner knowledge into a real world model and execution decision context, then replace uniform retry with classified recovery, add graph-level feedback nodes, persist site learning snapshots, and finally delete the old runtime state fallbacks once the new flow is the only writer.

**Tech Stack:** Python 3.11, LangGraph, Pydantic, SQLAlchemy, pytest, Playwright-facing pipeline modules

---

## Scope Note

The approved design spans multiple subsystems, so this implementation plan is split into seven milestones that each leave the repo in a working, testable state. The milestones are ordered so that every later task builds on contracts introduced in earlier tasks.

## File Structure

### New Files

- `src/autospider/graph/workflow_state.py` — canonical domain-shaped runtime state types and empty-state helpers
- `src/autospider/graph/workflow_access.py` — single-source accessors plus explicit legacy-to-workflow adapter
- `src/autospider/graph/world_model.py` — page model, hypothesis, evidence, and world-model mutation helpers
- `src/autospider/graph/control_types.py` — plan spec, dispatch decision, recovery directive, and default policy helpers
- `src/autospider/graph/decision_context.py` — execution LLM context builder and prompt-friendly summarizers
- `src/autospider/graph/failures.py` — failure categories, failure records, and failure classification helpers
- `src/autospider/graph/recovery.py` — recovery policy selection and retry/backoff directives
- `src/autospider/graph/nodes/planning_nodes.py` — workflow-aware world-model initialization and plan strategy nodes
- `src/autospider/graph/nodes/feedback_nodes.py` — dispatch monitoring, world-model update, and replan routing nodes
- `tests/test_workflow_state_access.py` — coverage for canonical workflow access and legacy adapter behavior
- `tests/test_decision_context.py` — coverage for world model + decision context contracts
- `tests/test_planner_world_model.py` — coverage for planner result to workflow state conversion
- `tests/test_failure_classifier.py` — coverage for failure categories and recovery directives
- `tests/test_feedback_nodes.py` — coverage for monitor/update/replan graph nodes
- `tests/test_pipeline_learning_persistence.py` — coverage for site profile and failure pattern persistence

### Existing Files To Modify

- `src/autospider/graph/state.py` — expose new workflow contracts during migration, then remove legacy shells in the last milestone
- `src/autospider/graph/state_access.py` — route old selectors through explicit workflow adapters, then drop fallback reads
- `src/autospider/graph/main_graph.py` — insert planning and feedback layers around the dispatch loop
- `src/autospider/graph/nodes/entry_nodes.py` — write `intent` state and normalized execution seed
- `src/autospider/graph/nodes/capability_nodes.py` — emit world/control state, then delegate recovery to classifier-driven helper
- `src/autospider/graph/subgraphs/multi_dispatch.py` — read `control.current_plan`, emit execution failures, and preserve workflow namespaces
- `src/autospider/crawler/planner/task_planner.py` — expose planner analysis needed to seed page models and success criteria
- `src/autospider/crawler/collector/llm_decision.py` — consume decision context instead of raw task text only
- `src/autospider/field/field_decider.py` — consume decision context and recent failures in prompts
- `src/autospider/common/protocol.py` — expose protocol diagnostics instead of returning only `None`
- `src/autospider/common/llm/decider.py` — convert invalid protocol outputs into explicit contract-violation failures
- `src/autospider/pipeline/types.py` — carry world snapshots, decision context, and failure records through execution contracts
- `src/autospider/pipeline/helpers.py` — build execution context with decision-context payloads
- `src/autospider/pipeline/runner.py` — thread decision context and failure records into collector/extractor runtime
- `src/autospider/pipeline/finalization.py` — persist world snapshots, site profile snapshots, and failure patterns
- `src/autospider/common/db/models.py` — extend `task_runs` snapshot storage for world/learning payloads
- `src/autospider/common/db/repositories/task_repo.py` — save and rehydrate new learning snapshot fields
- `src/autospider/common/storage/task_run_query_service.py` — expose read-side lookup for site profile snapshots
- `tests/test_graph_state_access.py` — redirect existing assertions to new workflow-backed selectors
- `tests/test_main_graph.py` — cover new graph routes
- `tests/test_pipeline_finalization.py` — cover learning persistence in finalization
- `tests/test_pipeline_runtime_integration.py` — cover execution context propagation

### Responsibilities By Milestone

- Milestone 1 owns state contracts and adapters.
- Milestone 2 owns world model and execution context contracts.
- Milestone 3 owns planner-to-execution knowledge propagation.
- Milestone 4 owns failure classification and recovery behavior.
- Milestone 5 owns graph control-layer insertion.
- Milestone 6 owns persistence and learning snapshots.
- Milestone 7 owns legacy field deletion and final contract cleanup.

### Task 1: Introduce Workflow State And Explicit Legacy Adapter

**Files:**
- Create: `src/autospider/graph/workflow_state.py`
- Create: `src/autospider/graph/workflow_access.py`
- Modify: `src/autospider/graph/state.py`
- Modify: `src/autospider/graph/state_access.py`
- Create: `tests/test_workflow_state_access.py`
- Modify: `tests/test_graph_state_access.py`

- [ ] **Step 1: Write the failing adapter/accessor tests**

```python
# tests/test_workflow_state_access.py
from autospider.graph.workflow_access import (
    coerce_workflow_state,
    current_plan,
    final_error,
    intent_fields,
)


def test_coerce_legacy_graph_state_into_workflow_state() -> None:
    legacy = {
        "thread_id": "thread-1",
        "conversation": {
            "status": "ok",
            "clarified_task": {
                "task_description": "采集新闻标题",
                "fields": [
                    {"name": "title", "description": "标题"},
                    {"name": "published_at", "description": "发布时间"},
                ],
            },
            "selected_skills": [{"name": "news-site"}],
        },
        "planning": {"status": "ok", "task_plan": {"plan_id": "plan-1"}},
        "result": {"summary": {"merged_items": 3}},
    }

    workflow = coerce_workflow_state(legacy)

    assert workflow["meta"]["thread_id"] == "thread-1"
    assert workflow["intent"]["clarified_task"]["task_description"] == "采集新闻标题"
    assert workflow["intent"]["fields"][0]["name"] == "title"
    assert workflow["control"]["current_plan"]["plan_id"] == "plan-1"
    assert workflow["result"]["summary"]["merged_items"] == 3


def test_current_plan_reads_control_namespace_only() -> None:
    state = {"control": {"current_plan": {"plan_id": "plan-2", "objective": "collect"}}}

    assert current_plan(state) == {"plan_id": "plan-2", "objective": "collect"}


def test_final_error_prefers_result_final_error() -> None:
    state = {"result": {"final_error": {"code": "fatal", "message": "boom"}}}

    assert final_error(state) == {"code": "fatal", "message": "boom"}


def test_intent_fields_read_from_workflow_state() -> None:
    state = {
        "intent": {
            "fields": [
                {"name": "title", "description": "标题"},
                {"name": "url", "description": "详情页链接"},
            ]
        }
    }

    assert [field["name"] for field in intent_fields(state)] == ["title", "url"]
```

- [ ] **Step 2: Run the new and existing state tests to verify they fail**

Run: `pytest tests/test_workflow_state_access.py tests/test_graph_state_access.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'autospider.graph.workflow_state'` and/or import failures from `autospider.graph.workflow_access`.

- [ ] **Step 3: Implement workflow state types, explicit adapter, and compatibility-backed selectors**

```python
# src/autospider/graph/workflow_state.py
from __future__ import annotations

from typing import Any, TypedDict


class MetaState(TypedDict, total=False):
    thread_id: str
    request_id: str
    entry_mode: str
    lifecycle_status: str


class IntentState(TypedDict, total=False):
    status: str
    request_text: str
    clarified_task: dict[str, Any] | None
    fields: list[dict[str, Any]]
    constraints: dict[str, Any]
    chat_history: list[dict[str, str]]
    selected_skills: list[dict[str, str]]
    clarification_trace: list[dict[str, Any]]


class WorldModelState(TypedDict, total=False):
    site_profile: dict[str, Any]
    page_models: dict[str, dict[str, Any]]
    navigation_memory: dict[str, Any]
    extraction_memory: dict[str, Any]
    active_hypotheses: list[dict[str, Any]]
    invalidated_hypotheses: list[dict[str, Any]]
    evidence_log: list[dict[str, Any]]


class ControlState(TypedDict, total=False):
    current_plan: dict[str, Any] | None
    dispatch_policy: dict[str, Any]
    active_strategy: dict[str, Any]
    recovery_policy: dict[str, Any]
    decision_context: dict[str, Any]
    checkpoints: list[dict[str, Any]]


class ExecutionState(TypedDict, total=False):
    stage: str
    current_subtask: dict[str, Any] | None
    runtime_context: dict[str, Any]
    collected_urls: list[str]
    collection_config: dict[str, Any] | None
    extraction_config: dict[str, Any] | None
    action_trace: list[dict[str, Any]]
    failures: list[dict[str, Any]]


class ResultState(TypedDict, total=False):
    summary: dict[str, Any]
    artifacts: list[dict[str, str]]
    final_error: dict[str, str] | None


class WorkflowState(TypedDict, total=False):
    meta: MetaState
    intent: IntentState
    world: WorldModelState
    control: ControlState
    execution: ExecutionState
    result: ResultState
```

```python
# src/autospider/graph/workflow_access.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .workflow_state import WorkflowState


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def coerce_workflow_state(state: Mapping[str, Any] | None) -> WorkflowState:
    graph_state = _as_dict(state)
    if {"meta", "intent", "world", "control", "execution", "result"} <= set(graph_state):
        return dict(graph_state)  # type: ignore[return-value]

    conversation = _as_dict(graph_state.get("conversation"))
    planning = _as_dict(graph_state.get("planning"))
    result = _as_dict(graph_state.get("result"))
    clarified_task = _as_dict(conversation.get("clarified_task"))

    return {
        "meta": {
            "thread_id": str(graph_state.get("thread_id") or ""),
            "request_id": str(graph_state.get("request_id") or ""),
            "entry_mode": str(graph_state.get("entry_mode") or ""),
            "lifecycle_status": str(graph_state.get("status") or ""),
        },
        "intent": {
            "status": str(conversation.get("status") or ""),
            "request_text": str(_as_dict(graph_state.get("normalized_params")).get("request") or ""),
            "clarified_task": clarified_task or None,
            "fields": list(clarified_task.get("fields") or []),
            "constraints": {},
            "chat_history": list(conversation.get("chat_history") or []),
            "selected_skills": list(conversation.get("selected_skills") or []),
            "clarification_trace": [],
        },
        "world": {
            "site_profile": {},
            "page_models": {},
            "navigation_memory": {},
            "extraction_memory": {},
            "active_hypotheses": [],
            "invalidated_hypotheses": [],
            "evidence_log": [],
        },
        "control": {
            "current_plan": _as_dict(planning.get("task_plan") or graph_state.get("task_plan")) or None,
            "dispatch_policy": {},
            "active_strategy": {},
            "recovery_policy": {},
            "decision_context": {},
            "checkpoints": [],
        },
        "execution": {
            "stage": "",
            "current_subtask": None,
            "runtime_context": {},
            "collected_urls": [],
            "collection_config": None,
            "extraction_config": None,
            "action_trace": [],
            "failures": [],
        },
        "result": {
            "summary": _as_dict(result.get("summary") or graph_state.get("summary")),
            "artifacts": list(result.get("artifacts") or graph_state.get("artifacts") or []),
            "final_error": _as_dict(result.get("error") or graph_state.get("error") or graph_state.get("node_error")) or None,
        },
    }


def current_plan(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return _as_dict(_as_dict(coerce_workflow_state(state).get("control")).get("current_plan")) or None


def intent_fields(state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return list(_as_dict(coerce_workflow_state(state).get("intent")).get("fields") or [])


def final_error(state: Mapping[str, Any] | None) -> dict[str, str]:
    return dict(_as_dict(coerce_workflow_state(state).get("result")).get("final_error") or {})
```

```python
# src/autospider/graph/state_access.py
from .workflow_access import coerce_workflow_state, current_plan, final_error


def task_plan(state):
    return current_plan(state)


def get_error_state(state):
    return final_error(state)


def get_result_summary(state):
    workflow = coerce_workflow_state(state)
    return dict(workflow.get("result", {}).get("summary") or {})
```

```python
# src/autospider/graph/state.py
from .workflow_state import (
    ControlState,
    ExecutionState,
    IntentState,
    MetaState,
    ResultState,
    WorkflowState,
    WorldModelState,
)
```

- [ ] **Step 4: Run the state tests to verify the adapter layer passes**

Run: `pytest tests/test_workflow_state_access.py tests/test_graph_state_access.py -q`

Expected: PASS with all state-access tests green.

- [ ] **Step 5: Commit the workflow-state foundation**

```bash
git add tests/test_workflow_state_access.py tests/test_graph_state_access.py src/autospider/graph/workflow_state.py src/autospider/graph/workflow_access.py src/autospider/graph/state.py src/autospider/graph/state_access.py
git commit -m "feat: add workflow state foundation"
```

### Task 2: Add World Model, Control Contracts, And Decision Context

**Files:**
- Create: `src/autospider/graph/world_model.py`
- Create: `src/autospider/graph/control_types.py`
- Create: `src/autospider/graph/decision_context.py`
- Modify: `src/autospider/pipeline/types.py`
- Modify: `src/autospider/pipeline/helpers.py`
- Create: `tests/test_decision_context.py`
- Modify: `tests/test_pipeline_runtime_integration.py`

- [ ] **Step 1: Write the failing world-model and decision-context tests**

```python
# tests/test_decision_context.py
from autospider.graph.control_types import build_default_dispatch_policy, build_default_recovery_policy
from autospider.graph.decision_context import build_decision_context


def test_build_decision_context_includes_page_model_and_recent_failures() -> None:
    workflow = {
        "intent": {
            "clarified_task": {"task_description": "采集新闻标题"},
            "fields": [{"name": "title", "description": "标题"}],
            "selected_skills": [{"name": "news-site"}],
        },
        "world": {
            "page_models": {
                "entry": {
                    "page_id": "entry",
                    "page_type": "list_page",
                    "structural_features": {"pagination": "next_link"},
                    "extraction_hints": {"title_xpath": "//h1"},
                }
            },
            "active_hypotheses": [{"hypothesis_id": "h-1", "statement": "entry is a list page"}],
        },
        "control": {
            "current_plan": {"success_criteria": {"target_url_count": 10}},
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
        "execution": {
            "failures": [{"code": "loop", "category": "STATE_MISMATCH", "message": "loop detected"}],
            "action_trace": [{"action": "scroll"}],
        },
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["page_model"]["page_type"] == "list_page"
    assert context["recent_failures"][0]["category"] == "STATE_MISMATCH"
    assert context["success_criteria"]["target_url_count"] == 10
```

```python
# tests/test_pipeline_runtime_integration.py
from autospider.pipeline.types import ExecutionRequest


def test_execution_request_from_params_preserves_decision_payload() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/list",
            "task_description": "collect news",
            "decision_context": {"page_model": {"page_type": "list_page"}},
            "world_snapshot": {"site_profile": {"host": "example.com"}},
            "failure_records": [{"code": "loop", "category": "STATE_MISMATCH"}],
        }
    )

    assert request.decision_context["page_model"]["page_type"] == "list_page"
    assert request.world_snapshot["site_profile"]["host"] == "example.com"
    assert request.failure_records[0]["code"] == "loop"
```

- [ ] **Step 2: Run the decision-context tests to verify they fail**

Run: `pytest tests/test_decision_context.py tests/test_pipeline_runtime_integration.py -q`

Expected: FAIL with `ModuleNotFoundError` for the new graph contract modules and missing `decision_context` / `world_snapshot` fields on `ExecutionRequest`.

- [ ] **Step 3: Implement world-model helpers, control contracts, and execution payload fields**

```python
# src/autospider/graph/control_types.py
from __future__ import annotations

from typing import Any, TypedDict


class PlanSpec(TypedDict, total=False):
    plan_id: str
    objective: str
    subtasks: list[dict[str, Any]]
    success_criteria: dict[str, Any]
    assumptions: list[str]
    risk_points: list[str]


class DispatchDecision(TypedDict, total=False):
    subtask_id: str
    strategy: str
    priority: int
    recovery_mode: str
    hints: dict[str, Any]


class RecoveryDirective(TypedDict, total=False):
    action: str
    reason: str
    updates_world_model: bool
    replan_required: bool
    requires_human: bool


def build_default_dispatch_policy() -> dict[str, Any]:
    return {"batch_mode": "parallel", "max_replans": 1, "default_strategy": "collect"}


def build_default_recovery_policy() -> dict[str, Any]:
    return {
        "transient_retries": [1.0, 2.0, 4.0],
        "contract_violation": "reask",
        "state_mismatch": "replan",
        "site_defense": "human_intervention",
        "rule_stale": "refresh_rules",
    }
```

```python
# src/autospider/graph/world_model.py
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def build_initial_world_model(*, site_url: str, request_text: str, selected_skills: list[dict[str, str]] | None = None) -> dict[str, Any]:
    host = urlparse(str(site_url or "")).netloc.lower()
    return {
        "site_profile": {"host": host, "request_text": request_text, "selected_skills": list(selected_skills or [])},
        "page_models": {},
        "navigation_memory": {},
        "extraction_memory": {},
        "active_hypotheses": [],
        "invalidated_hypotheses": [],
        "evidence_log": [],
    }


def upsert_page_model(world: dict[str, Any], *, page_id: str, page_model: dict[str, Any]) -> dict[str, Any]:
    updated = dict(world)
    page_models = dict(updated.get("page_models") or {})
    page_models[page_id] = dict(page_model)
    updated["page_models"] = page_models
    return updated
```

```python
# src/autospider/graph/decision_context.py
from __future__ import annotations

from typing import Any


def build_decision_context(workflow: dict[str, Any], *, page_id: str | None = None) -> dict[str, Any]:
    world = dict(workflow.get("world") or {})
    control = dict(workflow.get("control") or {})
    execution = dict(workflow.get("execution") or {})
    page_models = dict(world.get("page_models") or {})
    chosen_page_id = page_id or next(iter(page_models.keys()), "")
    return {
        "intent": dict(workflow.get("intent") or {}),
        "page_model": dict(page_models.get(chosen_page_id) or {}),
        "active_hypotheses": list(world.get("active_hypotheses") or []),
        "selected_skills_context": str(control.get("selected_skills_context") or ""),
        "recent_failures": list(execution.get("failures") or [])[-5:],
        "recent_actions": list(execution.get("action_trace") or [])[-10:],
        "success_criteria": dict(dict(control.get("current_plan") or {}).get("success_criteria") or {}),
    }


def summarize_page_model(page_model: dict[str, Any] | None) -> str:
    model = dict(page_model or {})
    if not model:
        return "无页面模型"
    return f"page_type={model.get('page_type', '')}; features={model.get('structural_features', {})}; hints={model.get('extraction_hints', {})}"


def summarize_failures(failures: list[dict[str, Any]] | None) -> str:
    items = [f"{item.get('category', '')}:{item.get('message', '')}" for item in list(failures or [])]
    return " | ".join(item for item in items if item) or "无最近失败"
```

```python
# src/autospider/pipeline/types.py
class ExecutionRequest(BaseModel):
    list_url: str = ""
    task_description: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)
    output_dir: str = "output"
    decision_context: dict[str, Any] = Field(default_factory=dict)
    world_snapshot: dict[str, Any] = Field(default_factory=dict)
    failure_records: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_params(cls, params: dict[str, Any], *, thread_id: str = "", guard_intervention_mode: str = "interrupt") -> "ExecutionRequest":
        payload = dict(params or {})
        return cls(
            list_url=str(payload.get("list_url") or "").strip(),
            task_description=str(payload.get("task_description") or "").strip(),
            fields=list(payload.get("fields") or []),
            output_dir=str(payload.get("output_dir") or "output"),
            decision_context=dict(payload.get("decision_context") or {}),
            world_snapshot=dict(payload.get("world_snapshot") or {}),
            failure_records=list(payload.get("failure_records") or []),
        )
```

```python
# src/autospider/pipeline/helpers.py
def build_execution_context(request: ExecutionRequest, *, fields: list[Any] | None = None) -> ExecutionContext:
    return ExecutionContext(
        request=request,
        identity=identity,
        fields=tuple(list(fields or [])),
        pipeline_mode=pipeline_mode,
        consumer_concurrency=resolved.consumer_concurrency,
        max_concurrent=resolved.max_concurrent,
        global_browser_budget=resolved.global_browser_budget,
        resume_mode=request.resume_mode,
        execution_id=str(request.execution_id or "").strip(),
        decision_context=dict(request.decision_context or {}),
        world_snapshot=dict(request.world_snapshot or {}),
        failure_records=tuple(list(request.failure_records or [])),
    )
```

- [ ] **Step 4: Run the contract tests to verify the new payloads pass**

Run: `pytest tests/test_decision_context.py tests/test_pipeline_runtime_integration.py -q`

Expected: PASS with decision-context and execution-contract assertions green.

- [ ] **Step 5: Commit the world-model and control contracts**

```bash
git add tests/test_decision_context.py tests/test_pipeline_runtime_integration.py src/autospider/graph/world_model.py src/autospider/graph/control_types.py src/autospider/graph/decision_context.py src/autospider/pipeline/types.py src/autospider/pipeline/helpers.py
git commit -m "feat: add world model and decision context contracts"
```

### Task 3: Seed The World Model From Planner And Feed Decision Context Into Execution

**Files:**
- Modify: `src/autospider/graph/nodes/entry_nodes.py`
- Modify: `src/autospider/graph/nodes/capability_nodes.py`
- Modify: `src/autospider/crawler/planner/task_planner.py`
- Modify: `src/autospider/crawler/collector/llm_decision.py`
- Modify: `src/autospider/field/field_decider.py`
- Modify: `src/autospider/pipeline/runner.py`
- Create: `tests/test_planner_world_model.py`
- Modify: `tests/test_decision_context.py`

- [ ] **Step 1: Write the failing planner-to-world-model tests**

```python
# tests/test_planner_world_model.py
from autospider.graph.control_types import build_default_dispatch_policy, build_default_recovery_policy
from autospider.graph.decision_context import build_decision_context
from autospider.graph.world_model import build_initial_world_model, upsert_page_model


def test_plan_node_payload_includes_world_and_control_sections() -> None:
    world = build_initial_world_model(
        site_url="https://example.com/news",
        request_text="采集新闻标题和发布时间",
        selected_skills=[{"name": "news-site"}],
    )
    world = upsert_page_model(
        world,
        page_id="entry",
        page_model={
            "page_id": "entry",
            "page_type": "category_page",
            "structural_features": {"nav": "tabs"},
            "extraction_hints": {},
        },
    )
    workflow = {
        "intent": {
            "clarified_task": {"task_description": "采集新闻标题和发布时间"},
            "fields": [
                {"name": "title", "description": "标题"},
                {"name": "published_at", "description": "发布时间"},
            ],
        },
        "world": world,
        "control": {
            "current_plan": {
                "plan_id": "plan-1",
                "objective": "采集新闻标题和发布时间",
                "success_criteria": {"target_url_count": 20, "required_fields": ["title", "published_at"]},
            },
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
        "execution": {"failures": [], "action_trace": []},
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["page_model"]["page_type"] == "category_page"
    assert context["success_criteria"]["required_fields"] == ["title", "published_at"]
```

- [ ] **Step 2: Run the planner-to-execution tests to verify they fail**

Run: `pytest tests/test_planner_world_model.py tests/test_decision_context.py -q`

Expected: FAIL because planner nodes do not yet populate `world`/`control` state and collector/extractor prompt builders do not accept decision context.

- [ ] **Step 3: Emit world/control payloads from planning and feed decision context into collector and extractor**

```python
# src/autospider/graph/nodes/capability_nodes.py
from ...graph.control_types import build_default_dispatch_policy, build_default_recovery_policy
from ...graph.decision_context import build_decision_context
from ...graph.world_model import build_initial_world_model, upsert_page_model


def _build_plan_spec(request, plan) -> dict[str, Any]:
    return {
        "plan_id": str(getattr(plan, "plan_id", "") or ""),
        "objective": str(request.task_description or request.request or ""),
        "subtasks": [subtask.model_dump(mode="python") for subtask in list(plan.subtasks or [])],
        "success_criteria": {
            "target_url_count": request.target_url_count,
            "required_fields": [str(field.get("name") or "") for field in list(request.fields or [])],
        },
        "assumptions": [],
        "risk_points": [],
    }


def _build_world_and_control_payload(request, plan, selected_skills: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    world = build_initial_world_model(
        site_url=request.site_url or request.list_url,
        request_text=request.request or request.task_description,
        selected_skills=selected_skills,
    )
    page_type = "unknown"
    if list(getattr(plan, "nodes", []) or []):
        page_type = str(getattr(plan.nodes[0], "node_type", "") or "unknown")
    world = upsert_page_model(
        world,
        page_id="entry",
        page_model={
            "page_id": "entry",
            "url_pattern": request.site_url or request.list_url,
            "page_type": page_type,
            "structural_features": {},
            "extraction_hints": {"shared_fields": list(request.fields or [])},
            "confidence": 0.8,
            "source": "planner",
        },
    )
    control = {
        "current_plan": _build_plan_spec(request, plan),
        "dispatch_policy": build_default_dispatch_policy(),
        "active_strategy": {"name": "collect"},
        "recovery_policy": build_default_recovery_policy(),
        "decision_context": {},
        "checkpoints": [],
        "selected_skills_context": "",
    }
    return world, control
```

```python
# src/autospider/crawler/collector/llm_decision.py
from ...graph.decision_context import summarize_failures, summarize_page_model


class LLMDecisionMaker:
    def __init__(
        self,
        page: "Page",
        decider: "LLMDecider",
        task_description: str,
        collected_urls: list[str],
        visited_detail_urls: set[str],
        list_url: str,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        execution_brief: dict | None = None,
        decision_context: dict | None = None,
    ):
        self.decision_context = dict(decision_context or {})

    async def ask_for_decision(
        self,
        snapshot: "SoMSnapshot",
        screenshot_base64: str = "",
        validation_feedback: str = "",
    ) -> dict | None:
        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="ask_llm_decision_user_message",
            variables={
                "task_description": self.task_description,
                "current_url": self.page.url,
                "visited_count": len(self.visited_detail_urls),
                "collected_urls_str": "\n".join(self.collected_urls[:10]) or "暂无",
                "execution_brief": format_execution_brief(self.execution_brief),
                "selected_skills_context": self.selected_skills_context or "当前未选择任何站点 skills。",
                "page_model_summary": summarize_page_model(self.decision_context.get("page_model")),
                "recent_failures_summary": summarize_failures(self.decision_context.get("recent_failures")),
                "success_criteria_summary": str(self.decision_context.get("success_criteria") or {}),
            },
        )
```

```python
# src/autospider/field/field_decider.py
from ..graph.decision_context import summarize_failures, summarize_page_model


class FieldDecider:
    def __init__(
        self,
        page: "Page",
        decider: "LLMDecider",
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        decision_context: dict | None = None,
    ):
        self.decision_context = dict(decision_context or {})

    async def decide_navigation(
        self,
        snapshot: "SoMSnapshot",
        screenshot_base64: str,
        field: FieldDefinition,
        nav_steps_count: int = 0,
        nav_steps_summary: str | None = None,
        scroll_info: "ScrollInfo | None" = None,
        page_text_hit: bool | None = None,
    ) -> dict | None:
        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="navigate_to_field_user_message",
            variables={
                "field_name": field.name,
                "field_description": field.description,
                "field_example": field.example or "",
                "current_url": self.page.url,
                "nav_steps_count": nav_steps_count,
                "nav_steps_summary": nav_steps_summary or "无",
                "page_model_summary": summarize_page_model(self.decision_context.get("page_model")),
                "recent_failures_summary": summarize_failures(self.decision_context.get("recent_failures")),
                "success_criteria_summary": str(self.decision_context.get("success_criteria") or {}),
            },
        )
```

```python
# src/autospider/pipeline/runner.py
runtime_context = PipelineRuntimeContext(
    list_url=list_url,
    task_description=task_description,
    output_dir=output_dir,
    consumer_workers=consumer_workers,
    decision_context=dict(context.decision_context or {}),
    world_snapshot=dict(context.world_snapshot or {}),
    failure_records=list(context.failure_records or []),
)
```

- [ ] **Step 4: Run the planner/world-model tests to verify the execution context is now seeded**

Run: `pytest tests/test_planner_world_model.py tests/test_decision_context.py -q`

Expected: PASS with world-model seeding and decision-context propagation assertions green.

- [ ] **Step 5: Commit planner-to-execution knowledge propagation**

```bash
git add tests/test_planner_world_model.py tests/test_decision_context.py src/autospider/graph/nodes/entry_nodes.py src/autospider/graph/nodes/capability_nodes.py src/autospider/crawler/planner/task_planner.py src/autospider/crawler/collector/llm_decision.py src/autospider/field/field_decider.py src/autospider/pipeline/runner.py
git commit -m "feat: propagate planner knowledge into execution context"
```

### Task 4: Replace Uniform Retry With Failure Classification And Recovery Directives

**Files:**
- Create: `src/autospider/graph/failures.py`
- Create: `src/autospider/graph/recovery.py`
- Modify: `src/autospider/common/protocol.py`
- Modify: `src/autospider/common/llm/decider.py`
- Modify: `src/autospider/graph/nodes/capability_nodes.py`
- Create: `tests/test_failure_classifier.py`

- [ ] **Step 1: Write the failing failure-classification and protocol-diagnostics tests**

```python
# tests/test_failure_classifier.py
from autospider.common.protocol import parse_protocol_message_diagnostics
from autospider.graph.failures import classify_protocol_violation, classify_runtime_exception


def test_parse_protocol_message_diagnostics_returns_validation_errors() -> None:
    diagnostics = parse_protocol_message_diagnostics({"action": "click", "args": {}})

    assert diagnostics["message"] is None
    assert diagnostics["errors"]


def test_classify_protocol_violation_marks_strategy_switch() -> None:
    failure = classify_protocol_violation(
        stage="collector_decision",
        errors=["click requires target_text or mark_id"],
        payload={"action": "click", "args": {}},
    )

    assert failure["category"] == "CONTRACT_VIOLATION"
    assert failure["retryable"] is False
    assert failure["requires_strategy_switch"] is True


def test_classify_runtime_exception_marks_transient_timeout() -> None:
    failure = classify_runtime_exception(
        TimeoutError("socket timeout"),
        stage="plan_node",
        context={"list_url": "https://example.com"},
    )

    assert failure["category"] == "TRANSIENT"
    assert failure["retryable"] is True
```

- [ ] **Step 2: Run the failure tests to verify they fail**

Run: `pytest tests/test_failure_classifier.py -q`

Expected: FAIL because `parse_protocol_message_diagnostics`, `classify_protocol_violation`, and `classify_runtime_exception` do not exist yet.

- [ ] **Step 3: Implement failure records, diagnostics, and recovery-driven execution**

```python
# src/autospider/graph/failures.py
from __future__ import annotations

from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    STATE_MISMATCH = "STATE_MISMATCH"
    SITE_DEFENSE = "SITE_DEFENSE"
    RULE_STALE = "RULE_STALE"
    FATAL = "FATAL"


def build_failure_record(*, code: str, category: FailureCategory, stage: str, message: str, context: dict[str, Any], retryable: bool, requires_strategy_switch: bool, requires_human: bool) -> dict[str, Any]:
    return {
        "code": code,
        "category": category.value,
        "stage": stage,
        "message": message,
        "cause": message,
        "retryable": retryable,
        "requires_strategy_switch": requires_strategy_switch,
        "requires_human": requires_human,
        "context": dict(context or {}),
        "attempted_recoveries": [],
    }


def classify_protocol_violation(*, stage: str, errors: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    message = "; ".join(errors) or "invalid_protocol_message"
    return build_failure_record(
        code="protocol_contract_violation",
        category=FailureCategory.CONTRACT_VIOLATION,
        stage=stage,
        message=message,
        context={"payload": dict(payload or {})},
        retryable=False,
        requires_strategy_switch=True,
        requires_human=False,
    )


def classify_runtime_exception(exc: Exception, *, stage: str, context: dict[str, Any]) -> dict[str, Any]:
    text = str(exc or "").lower()
    if "timeout" in text:
        return build_failure_record(
            code="transient_timeout",
            category=FailureCategory.TRANSIENT,
            stage=stage,
            message=str(exc),
            context=context,
            retryable=True,
            requires_strategy_switch=False,
            requires_human=False,
        )
    return build_failure_record(
        code="fatal_runtime_error",
        category=FailureCategory.FATAL,
        stage=stage,
        message=str(exc),
        context=context,
        retryable=False,
        requires_strategy_switch=False,
        requires_human=False,
    )
```

```python
# src/autospider/graph/recovery.py
from __future__ import annotations


def build_recovery_directive(failure: dict[str, object], *, attempt: int, delays: list[float]) -> dict[str, object]:
    category = str(failure.get("category") or "")
    if category == "TRANSIENT" and attempt < len(delays):
        return {"action": "retry", "delay_s": delays[attempt], "replan_required": False}
    if category == "CONTRACT_VIOLATION":
        return {"action": "reask", "delay_s": 0.0, "replan_required": False}
    if category in {"STATE_MISMATCH", "RULE_STALE"}:
        return {"action": "replan", "delay_s": 0.0, "replan_required": True}
    if category == "SITE_DEFENSE":
        return {"action": "human_intervention", "delay_s": 0.0, "replan_required": False}
    return {"action": "fail", "delay_s": 0.0, "replan_required": False}
```

```python
# src/autospider/common/protocol.py
def parse_protocol_message_diagnostics(payload: Any | None) -> dict[str, Any]:
    if payload is None:
        return {"message": None, "errors": ["missing payload"], "action": "", "args": {}}
    data = payload if isinstance(payload, dict) else extract_json_dict_from_llm_payload(payload)
    if not isinstance(data, dict):
        return {"message": None, "errors": ["payload is not a dict"], "action": "", "args": {}}
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    args = dict(args)
    action = _normalize_action(data.get("action")) or _infer_action_from_args(args)
    action = _ACTION_ALIASES.get(action, action)
    if not action:
        return {"message": None, "errors": ["missing action"], "action": "", "args": args}
    validated, errors = validate_protocol_message_payload(
        action=action,
        args=args,
        thinking=_extract_response_thinking(payload),
    )
    return {"message": validated, "errors": errors, "action": action, "args": args}


def parse_protocol_message(payload: Any | None) -> dict[str, Any] | None:
    return parse_protocol_message_diagnostics(payload)["message"]
```

```python
# src/autospider/graph/nodes/capability_nodes.py
from ...graph.failures import classify_runtime_exception
from ...graph.recovery import build_recovery_directive


async def _run_with_recovery(runner, *, stage: str, context: dict[str, Any], error_code: str) -> dict[str, Any]:
    last_failure = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return await runner()
        except Exception as exc:  # noqa: BLE001
            last_failure = classify_runtime_exception(exc, stage=stage, context=context)
            directive = build_recovery_directive(last_failure, attempt=attempt, delays=list(RETRY_DELAYS))
            if directive["action"] != "retry":
                return {**_fatal(error_code, str(exc)), "execution": {"failures": [last_failure]}}
            await asyncio.sleep(float(directive["delay_s"]))
    return {**_fatal(error_code, str(last_failure.get("message") if last_failure else "unknown_error")), "execution": {"failures": [last_failure] if last_failure else []}}
```

- [ ] **Step 4: Run the failure tests to verify the recovery layer passes**

Run: `pytest tests/test_failure_classifier.py -q`

Expected: PASS with failure-classification and protocol-diagnostics assertions green.

- [ ] **Step 5: Commit the failure and recovery layer**

```bash
git add tests/test_failure_classifier.py src/autospider/graph/failures.py src/autospider/graph/recovery.py src/autospider/common/protocol.py src/autospider/common/llm/decider.py src/autospider/graph/nodes/capability_nodes.py
git commit -m "feat: add failure classification and recovery directives"
```

### Task 5: Insert Planning And Feedback Layers Into The Main Graph

**Files:**
- Create: `src/autospider/graph/nodes/planning_nodes.py`
- Create: `src/autospider/graph/nodes/feedback_nodes.py`
- Modify: `src/autospider/graph/main_graph.py`
- Modify: `src/autospider/graph/subgraphs/multi_dispatch.py`
- Create: `tests/test_feedback_nodes.py`
- Modify: `tests/test_main_graph.py`

- [ ] **Step 1: Write the failing graph-control tests**

```python
# tests/test_feedback_nodes.py
from autospider.graph.nodes.feedback_nodes import monitor_dispatch_node, route_after_feedback


def test_monitor_dispatch_marks_replan_for_state_mismatch_failures() -> None:
    state = {
        "execution": {
            "failures": [
                {"code": "loop", "category": "STATE_MISMATCH", "message": "loop detected"}
            ]
        },
        "control": {
            "active_strategy": {"name": "collect"},
            "checkpoints": [],
        },
    }

    result = monitor_dispatch_node(state)

    assert result["control"]["active_strategy"]["name"] == "replan"
    assert result["control"]["checkpoints"][-1]["action"] == "replan"


def test_route_after_feedback_returns_replan() -> None:
    state = {"control": {"active_strategy": {"name": "replan"}}}

    assert route_after_feedback(state) == "replan"
```

```python
# tests/test_main_graph.py
from autospider.graph.main_graph import resolve_feedback_route


def test_resolve_feedback_route_sends_replan_back_to_strategy_node() -> None:
    state = {"control": {"active_strategy": {"name": "replan"}}, "result": {"final_error": None}}

    assert resolve_feedback_route(state) == "plan_strategy_node"
```

- [ ] **Step 2: Run the graph-control tests to verify they fail**

Run: `pytest tests/test_feedback_nodes.py tests/test_main_graph.py -q`

Expected: FAIL with import errors for `planning_nodes` / `feedback_nodes` and missing `resolve_feedback_route`.

- [ ] **Step 3: Add graph-level planning and feedback nodes around dispatch**

```python
# src/autospider/graph/nodes/planning_nodes.py
from __future__ import annotations

from typing import Any

from ...graph.decision_context import build_decision_context
from ...graph.workflow_access import coerce_workflow_state
from .capability_nodes import plan_node as legacy_plan_node


def initialize_world_model_node(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return {"world": dict(workflow.get("world") or {}), "control": dict(workflow.get("control") or {})}


async def plan_strategy_node(state: dict[str, Any]) -> dict[str, Any]:
    updates = await legacy_plan_node(state)
    workflow = coerce_workflow_state({**state, **updates})
    control = dict(workflow.get("control") or {})
    control["decision_context"] = build_decision_context(workflow, page_id="entry")
    return {**updates, "control": control}
```

```python
# src/autospider/graph/nodes/feedback_nodes.py
from __future__ import annotations

from ...graph.workflow_access import coerce_workflow_state
from ...graph.world_model import upsert_page_model


def monitor_dispatch_node(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    failures = list(dict(workflow.get("execution") or {}).get("failures") or [])
    needs_replan = any(str(item.get("category") or "") == "STATE_MISMATCH" for item in failures)
    checkpoint = {"action": "replan" if needs_replan else "continue", "reason": failures[-1]["message"] if failures else "dispatch_completed"}
    control = dict(workflow.get("control") or {})
    control["active_strategy"] = {"name": "replan" if needs_replan else "continue"}
    control["checkpoints"] = [*list(control.get("checkpoints") or []), checkpoint]
    return {"control": control}


def update_world_model_node(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    world = dict(workflow.get("world") or {})
    failures = list(dict(workflow.get("execution") or {}).get("failures") or [])
    if failures:
        page_models = dict(world.get("page_models") or {})
        entry = dict(page_models.get("entry") or {})
        if entry:
            entry["confidence"] = 0.3
            world = upsert_page_model(world, page_id="entry", page_model=entry)
    return {"world": world}


def route_after_feedback(state: dict[str, Any]) -> str:
    strategy = str(dict(state.get("control") or {}).get("active_strategy", {}).get("name") or "")
    return "replan" if strategy == "replan" else "aggregate"
```

```python
# src/autospider/graph/main_graph.py
from .nodes.feedback_nodes import monitor_dispatch_node, route_after_feedback, update_world_model_node
from .nodes.planning_nodes import initialize_world_model_node, plan_strategy_node


def resolve_feedback_route(state: dict[str, Any]) -> str:
    route = route_after_feedback(state)
    return "plan_strategy_node" if route == "replan" else "aggregate_node"


graph.add_node("initialize_world_model_node", initialize_world_model_node)
graph.add_node("plan_strategy_node", plan_strategy_node)
graph.add_node("monitor_dispatch_node", monitor_dispatch_node)
graph.add_node("update_world_model_node", update_world_model_node)
```

- [ ] **Step 4: Run the graph-control tests to verify the new routing passes**

Run: `pytest tests/test_feedback_nodes.py tests/test_main_graph.py -q`

Expected: PASS with graph feedback routing green.

- [ ] **Step 5: Commit the graph control-layer changes**

```bash
git add tests/test_feedback_nodes.py tests/test_main_graph.py src/autospider/graph/nodes/planning_nodes.py src/autospider/graph/nodes/feedback_nodes.py src/autospider/graph/main_graph.py src/autospider/graph/subgraphs/multi_dispatch.py
git commit -m "feat: add planning and feedback graph layers"
```

### Task 6: Persist Site Profiles, World Snapshots, And Failure Patterns

**Files:**
- Modify: `src/autospider/common/db/models.py`
- Modify: `src/autospider/common/db/repositories/task_repo.py`
- Modify: `src/autospider/common/storage/task_run_query_service.py`
- Modify: `src/autospider/pipeline/finalization.py`
- Create: `tests/test_pipeline_learning_persistence.py`
- Modify: `tests/test_pipeline_finalization.py`

- [ ] **Step 1: Write the failing learning-persistence tests**

```python
# tests/test_pipeline_learning_persistence.py
from pathlib import Path
from types import SimpleNamespace

from autospider.pipeline import finalization


def test_build_task_run_payload_includes_world_snapshot_and_failure_patterns() -> None:
    context = finalization.PipelineFinalizationContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect news",
        execution_brief={},
        fields=[],
        thread_id="thread-1",
        output_dir="output",
        output_path=Path("output"),
        items_path=Path("output/items.jsonl"),
        summary_path=Path("output/summary.json"),
        staging_items_path=Path("output/items.next.jsonl"),
        staging_summary_path=Path("output/summary.next.json"),
        committed_records={},
        summary={"execution_id": "run-1"},
        runtime_state=SimpleNamespace(
            error=None,
            terminal_reason="",
            validation_failures=[],
            collection_config={},
            extraction_config={},
            extraction_evidence=[],
            world_snapshot={"site_profile": {"host": "example.com"}, "page_models": {"entry": {"page_type": "list_page"}}},
            failure_patterns=[{"pattern_id": "loop-detected", "trigger": "ABAB loop"}],
        ),
        plan_knowledge="",
        task_plan={},
        plan_journal=[],
        tracker=SimpleNamespace(mark_done=lambda status: None),
        sessions=SimpleNamespace(stop=lambda: None),
    )

    payload = finalization._build_task_run_payload(context, {})

    assert payload.world_snapshot["site_profile"]["host"] == "example.com"
    assert payload.failure_patterns[0]["pattern_id"] == "loop-detected"
```

- [ ] **Step 2: Run the learning-persistence tests to verify they fail**

Run: `pytest tests/test_pipeline_learning_persistence.py tests/test_pipeline_finalization.py -q`

Expected: FAIL because `PipelineFinalizationContext`, `TaskRunPayload`, and `TaskRun` do not yet include world snapshot and failure pattern fields.

- [ ] **Step 3: Extend DB payloads and finalization to persist learning snapshots**

```python
# src/autospider/common/db/models.py
class TaskRun(Base):
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    collection_config: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    extraction_config: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    world_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    site_profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict)
    failure_patterns: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, default=list)
```

```python
# src/autospider/common/db/repositories/task_repo.py
@dataclass(frozen=True, slots=True)
class TaskRunPayload:
    summary_json: dict[str, Any] = field(default_factory=dict)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    site_profile_snapshot: dict[str, Any] = field(default_factory=dict)
    failure_patterns: list[dict[str, Any]] = field(default_factory=list)
```

```python
# src/autospider/pipeline/finalization.py
from ..common.storage.task_run_query_service import normalize_url


def _build_failure_patterns(context: "PipelineFinalizationContext") -> list[dict[str, Any]]:
    runtime_patterns = list(getattr(context.runtime_state, "failure_patterns", []) or [])
    if runtime_patterns:
        return runtime_patterns
    return []


def _build_task_run_payload(context: "PipelineFinalizationContext", records: dict[str, dict]):
    normalized_url = normalize_url(context.list_url)
    world_snapshot = dict(getattr(context.runtime_state, "world_snapshot", {}) or {})
    site_profile_snapshot = dict(world_snapshot.get("site_profile") or {})
    failure_patterns = _build_failure_patterns(context)
    return TaskRunPayload(
        normalized_url=normalized_url,
        original_url=context.list_url,
        task_description=context.task_description,
        execution_id=str(context.summary.get("execution_id") or ""),
        summary_json=dict(context.summary or {}),
        collection_config=dict(context.runtime_state.collection_config or {}),
        extraction_config=dict(context.runtime_state.extraction_config or {}),
        world_snapshot=world_snapshot,
        site_profile_snapshot=site_profile_snapshot,
        failure_patterns=failure_patterns,
    )
```

```python
# src/autospider/common/storage/task_run_query_service.py
from autospider.common.db.engine import session_scope
from autospider.common.db.repositories.task_repo import TaskRepository


class TaskRunQueryService:
    def get_latest_site_profile(self, url: str) -> dict[str, Any] | None:
        rows = self.find_by_url(url)
        if not rows:
            return None
        with session_scope() as session:
            detail = TaskRepository(session).get_run_detail(str(rows[0].get("execution_id") or ""))
        if not detail:
            return None
        return dict(detail.get("run", {}).get("site_profile_snapshot") or {})
```

- [ ] **Step 4: Run the persistence tests to verify learning snapshots are durable**

Run: `pytest tests/test_pipeline_learning_persistence.py tests/test_pipeline_finalization.py -q`

Expected: PASS with world snapshot, site profile snapshot, and failure pattern persistence green.

- [ ] **Step 5: Commit learning persistence**

```bash
git add tests/test_pipeline_learning_persistence.py tests/test_pipeline_finalization.py src/autospider/common/db/models.py src/autospider/common/db/repositories/task_repo.py src/autospider/common/storage/task_run_query_service.py src/autospider/pipeline/finalization.py
git commit -m "feat: persist workflow learning snapshots"
```

### Task 7: Remove Legacy Runtime Fallbacks And Make Workflow State The Only Runtime Source

**Files:**
- Modify: `src/autospider/graph/state.py`
- Modify: `src/autospider/graph/state_access.py`
- Modify: `src/autospider/graph/main_graph.py`
- Modify: `src/autospider/pipeline/types.py`
- Modify: `tests/test_graph_state_access.py`
- Modify: `tests/test_pipeline_runtime_integration.py`
- Modify: `tests/test_main_graph.py`

- [ ] **Step 1: Write the failing cleanup tests that prohibit legacy runtime fields**

```python
# tests/test_graph_state_access.py
from autospider.graph.state_access import task_plan


def test_task_plan_no_longer_reads_legacy_root_field() -> None:
    state = {
        "control": {"current_plan": {"plan_id": "plan-1"}},
        "task_plan": {"plan_id": "stale-root-plan"},
    }

    assert task_plan(state) == {"plan_id": "plan-1"}
```

```python
# tests/test_pipeline_runtime_integration.py
from autospider.pipeline.types import ExecutionRequest


def test_execution_request_prefers_world_snapshot_over_plan_knowledge_for_runtime_context() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/list",
            "task_description": "collect",
            "world_snapshot": {"page_models": {"entry": {"page_type": "list_page"}}},
            "plan_knowledge": "stale-plan-knowledge",
        }
    )

    assert request.world_snapshot["page_models"]["entry"]["page_type"] == "list_page"
```

- [ ] **Step 2: Run the cleanup tests to verify they fail**

Run: `pytest tests/test_graph_state_access.py tests/test_pipeline_runtime_integration.py tests/test_main_graph.py -q`

Expected: FAIL because selectors still read legacy top-level state and runtime code still depends on old compatibility fields.

- [ ] **Step 3: Delete fallback reads and collapse the runtime to workflow-only namespaces**

```python
# src/autospider/graph/state.py
from .workflow_state import WorkflowState

GraphState = WorkflowState

__all__ = ["GraphState", "WorkflowState"]
```

```python
# src/autospider/graph/state_access.py
from .workflow_access import coerce_workflow_state


def task_plan(state):
    workflow = coerce_workflow_state(state)
    return dict(workflow.get("control", {}).get("current_plan") or {})


def get_error_state(state):
    workflow = coerce_workflow_state(state)
    return dict(workflow.get("result", {}).get("final_error") or {})
```

```python
# src/autospider/graph/main_graph.py
from .workflow_state import WorkflowState


def build_main_graph(*, checkpointer: Any | None = None):
    graph = StateGraph(WorkflowState)
    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("initialize_world_model_node", initialize_world_model_node)
    graph.add_node("plan_strategy_node", plan_strategy_node)
    graph.add_node("multi_dispatch_subgraph", build_multi_dispatch_subgraph())
    graph.add_node("monitor_dispatch_node", monitor_dispatch_node)
    graph.add_node("update_world_model_node", update_world_model_node)
```

- [ ] **Step 4: Run the cleanup regression tests and the core targeted suite**

Run: `pytest tests/test_workflow_state_access.py tests/test_graph_state_access.py tests/test_decision_context.py tests/test_failure_classifier.py tests/test_feedback_nodes.py tests/test_pipeline_learning_persistence.py tests/test_main_graph.py tests/test_pipeline_finalization.py tests/test_pipeline_runtime_integration.py -q`

Expected: PASS with the workflow-only runtime path green.

- [ ] **Step 5: Commit the final cleanup**

```bash
git add tests/test_workflow_state_access.py tests/test_graph_state_access.py tests/test_decision_context.py tests/test_failure_classifier.py tests/test_feedback_nodes.py tests/test_pipeline_learning_persistence.py tests/test_main_graph.py tests/test_pipeline_finalization.py tests/test_pipeline_runtime_integration.py src/autospider/graph/state.py src/autospider/graph/state_access.py src/autospider/graph/main_graph.py src/autospider/pipeline/types.py
git commit -m "refactor: make workflow state the runtime source of truth"
```
