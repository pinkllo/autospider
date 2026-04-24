from __future__ import annotations
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.composition.graph.control_types import (
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from autospider.composition.graph.decision_context import (
    build_decision_context,
    summarize_failures,
)
from autospider.composition.graph.nodes.capability_nodes import build_planning_runtime_payload
from autospider.composition.graph.world_model import build_initial_world_model, upsert_page_model
from autospider.platform.shared_kernel.knowledge_contracts import (
    DETAIL_FIELD_PROFILES_KEY,
    LIST_PAGE_PROFILE_KEY,
    VISUAL_DECISION_HINTS_KEY,
)


def test_build_default_policies_expose_control_contract_defaults() -> None:
    dispatch_policy = build_default_dispatch_policy()
    recovery_policy = build_default_recovery_policy()

    assert dispatch_policy.max_concurrency == 1
    assert dispatch_policy.strategy == "sequential"
    assert recovery_policy.max_retries == 2
    assert recovery_policy.fail_fast is True


def test_build_decision_context_reads_world_model_failures_and_success_criteria() -> None:
    world_model = build_initial_world_model(
        request_params={
            "list_url": "https://example.com/articles",
            "target_url_count": 8,
        }
    )
    world_model = upsert_page_model(
        world_model,
        page_id="entry",
        url="https://example.com/articles",
        page_type="list_page",
        links=14,
    )
    workflow = {
        "world": {
            "world_model": world_model,
            "failure_records": [
                {
                    "page_id": "entry",
                    "category": "navigation",
                    "detail": "timed_out",
                }
            ],
        },
        "control": {
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["page_model"]["page_type"] == "list_page"
    assert context["recent_failures"][0]["category"] == "navigation"
    assert context["success_criteria"]["target_url_count"] == 8


def test_build_decision_context_keeps_request_params_from_plain_world_model_mapping() -> None:
    workflow = {
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 8},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "list_page",
                    }
                },
                "failure_records": [],
            }
        },
        "control": {},
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["success_criteria"]["target_url_count"] == 8


def test_build_decision_context_prefers_world_request_params_over_world_model_snapshot() -> None:
    workflow = {
        "world": {
            "request_params": {"target_url_count": 12},
            "world_model": {
                "request_params": {"target_url_count": 3},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "list_page",
                    }
                },
                "failure_records": [],
            },
        },
        "control": {},
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["success_criteria"]["target_url_count"] == 12


def test_build_decision_context_ignores_adapter_injected_legacy_request_params_when_world_model_exists() -> (
    None
):
    state = {
        "normalized_params": {"keyword": "legacy-only"},
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 8},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "list_page",
                    }
                },
                "failure_records": [],
            }
        },
    }

    context = build_decision_context(state, page_id="entry")

    assert context["success_criteria"]["target_url_count"] == 8


def test_build_decision_context_parses_string_false_for_recovery_policy() -> None:
    context = build_decision_context(
        {
            "world": {
                "world_model": {
                    "request_params": {},
                    "page_models": {"entry": {"page_id": "entry", "page_type": "list_page"}},
                }
            },
            "control": {
                "recovery_policy": {"fail_fast": "false"},
            },
        },
        page_id="entry",
    )

    assert context["recovery_policy"]["fail_fast"] is False


def test_summarize_failures_returns_empty_for_non_positive_limits() -> None:
    failure_records = [
        {"page_id": "entry", "category": "navigation", "detail": "timeout"},
        {"page_id": "entry", "category": "parsing", "detail": "missing_field"},
    ]

    assert summarize_failures(failure_records, limit=0) == ()
    assert summarize_failures(failure_records, limit=-1) == ()


def test_build_decision_context_keeps_explicit_empty_world_failure_records() -> None:
    workflow = {
        "world": {
            "failure_records": [],
            "world_model": {
                "request_params": {"target_url_count": 8},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "list_page",
                    }
                },
                "failure_records": [{"page_id": "entry", "category": "old", "detail": "stale"}],
            },
        },
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["recent_failures"] == []


def test_build_decision_context_includes_structured_page_metadata_and_current_plan() -> None:
    workflow = {
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 8},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "category",
                        "metadata": {
                            "observations": "入口页识别为分类聚合页",
                            "shared_fields": [{"name": "title"}],
                        },
                    }
                },
                "failure_records": [],
            }
        },
        "control": {
            "current_plan": {
                "goal": "进入新闻列表页",
                "page_id": "entry",
                "stage": "planning_seeded",
            }
        },
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context["page_model"]["metadata"]["observations"] == "入口页识别为分类聚合页"
    assert context["page_model"]["metadata"]["shared_fields"] == [{"name": "title"}]
    assert context["current_plan"]["page_id"] == "entry"
    assert context["current_plan"]["goal"] == "进入新闻列表页"


def test_build_decision_context_normalizes_reusable_profile_metadata() -> None:
    workflow = {
        "world": {
            "world_model": {
                "request_params": {},
                "page_models": {
                    "entry": {
                        "page_id": "entry",
                        "page_type": "list_page",
                        "metadata": {
                            LIST_PAGE_PROFILE_KEY: {
                                "detail_xpath": "//a[@class='detail']",
                                "jump_input_selector": "//input[@type='number']",
                                "jump_button_selector": "//button[@type='submit']",
                            },
                            DETAIL_FIELD_PROFILES_KEY: [
                                {"name": "title", "primary_xpath": "//h1/text()"}
                            ],
                            VISUAL_DECISION_HINTS_KEY: [
                                {"purpose": "paginate", "xpath": "//a[@rel='next']"}
                            ],
                        },
                    }
                },
                "failure_records": [],
            }
        }
    }

    context = build_decision_context(workflow, page_id="entry")
    metadata = context["page_model"]["metadata"]

    assert metadata[LIST_PAGE_PROFILE_KEY]["common_detail_xpath"] == "//a[@class='detail']"
    assert metadata[LIST_PAGE_PROFILE_KEY]["jump_widget_xpath"] == {
        "input": "//input[@type='number']",
        "button": "//button[@type='submit']",
    }
    assert metadata[DETAIL_FIELD_PROFILES_KEY][0]["field_name"] == "title"
    assert metadata[DETAIL_FIELD_PROFILES_KEY][0]["xpath"] == "//h1/text()"
    assert metadata[VISUAL_DECISION_HINTS_KEY][0]["resolved_xpath"] == "//a[@rel='next']"


def test_build_planning_runtime_payload_enriches_request_params_with_execution_context() -> None:
    from autospider.contexts.planning.domain import (
        ExecutionBrief,
        PlanJournalEntry,
        PlanNode,
        PlanNodeType,
        SubTask,
        SubTaskMode,
        TaskPlan,
    )

    plan = TaskPlan(
        plan_id="plan_001",
        original_request="采集采购公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(
                id="leaf_001",
                name="采购公告",
                list_url="https://example.com/notices/purchase",
                anchor_url="https://example.com/notices",
                page_state_signature="sig-purchase",
                task_description="采集采购公告列表中的详情链接",
                mode=SubTaskMode.COLLECT,
                execution_brief=ExecutionBrief(objective="收集详情页链接"),
                plan_node_id="node_002",
            )
        ],
        nodes=[
            PlanNode(
                node_id="node_001",
                name="招标公告",
                node_type=PlanNodeType.CATEGORY,
                url="https://example.com/notices",
                task_description="进入招标公告列表",
                observations="入口页识别为分类页",
                children_count=1,
            )
        ],
        journal=[
            PlanJournalEntry(
                entry_id="journal_0001",
                node_id="node_001",
                phase="planning",
                action="analyze_page",
                reason="入口页识别为分类页",
                evidence="存在多个公告类型入口",
                metadata={},
                created_at="2026-04-12T10:00:00",
            )
        ],
        total_subtasks=1,
        shared_fields=[{"name": "title", "description": "公告标题"}],
        created_at="2026-04-12T10:00:00",
        updated_at="2026-04-12T10:00:01",
    )

    payload = build_planning_runtime_payload(
        plan=plan,
        plan_knowledge="structured planning knowledge",
        request_params={
            "list_url": "https://example.com/notices",
            "target_url_count": 8,
            "max_concurrent": 2,
        },
    )

    assert (
        payload["world"]["world_model"]["page_models"]["node_001"]["metadata"]["observations"]
        == "入口页识别为分类页"
    )
    assert payload["control"]["current_plan"]["page_id"] == "node_001"
    assert payload["decision_context"]["page_model"]["page_type"] == "category"
    assert payload["decision_context"]["current_plan"]["goal"] == "进入招标公告列表"
    assert payload["request_params"]["decision_context"] == payload["decision_context"]
    assert payload["request_params"]["world_snapshot"] == payload["world"]
    assert payload["request_params"]["failure_records"] == []

