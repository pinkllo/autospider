from __future__ import annotations
# ruff: noqa: E402

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import autospider.graph.nodes.entry_nodes as entry_nodes_module
from autospider.graph.state_access import request_params as select_request_params
from autospider.graph.nodes.entry_nodes import (
    chat_clarify,
    chat_history_match,
    chat_prepare_execution_handoff,
    chat_review_task,
    normalize_pipeline_params,
)
from autospider.contexts.chat.domain.model import (
    ClarificationResult,
    ClarificationSession,
    ClarifiedTask,
    DialogueMessage,
    RequestedField,
)
from autospider.pipeline.helpers import build_semantic_signature
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


def test_normalize_pipeline_params_exposes_empty_runtime_payload_slots() -> None:
    state = {
        "cli_args": {
            "list_url": "https://example.com/notices",
            "task_description": "采集公告",
            "output_dir": "output",
        }
    }

    result = normalize_pipeline_params(state)
    normalized = result["normalized_params"]

    assert "decision_context" in normalized
    assert "world_snapshot" in normalized
    assert "control_snapshot" in normalized
    assert "failure_records" in normalized
    assert normalized["decision_context"] == {}
    assert normalized["world_snapshot"] == {}
    assert normalized["control_snapshot"] == {}
    assert normalized["failure_records"] == []


def test_chat_prepare_execution_handoff_exposes_empty_runtime_payload_slots() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "采集公告",
        },
        "conversation": {
            "clarified_task": {
                "list_url": "https://example.com/notices",
                "task_description": "采集公告",
                "fields": [{"name": "title", "description": "公告标题", "required": True}],
                "max_pages": 3,
                "target_url_count": 8,
                "consumer_concurrency": 2,
                "field_explore_count": 1,
                "field_validate_count": 1,
            },
            "selected_skills": [],
        },
    }

    result = chat_prepare_execution_handoff(state)
    normalized = result["normalized_params"]

    assert normalized["decision_context"] == {}
    assert normalized["world_snapshot"] == {}
    assert normalized["control_snapshot"] == {}
    assert normalized["failure_records"] == []


def test_chat_prepare_execution_handoff_rejects_empty_list_url() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "采集公告",
        },
        "conversation": {
            "clarified_task": {
                "list_url": "",
                "task_description": "采集公告",
                "fields": [{"name": "title", "description": "公告标题", "required": True}],
            },
            "selected_skills": [],
        },
    }

    result = chat_prepare_execution_handoff(state)

    assert result["node_status"] == "fatal"
    assert result["error_code"] == "missing_list_url"


def test_request_params_falls_back_when_workflow_request_params_is_missing() -> None:
    state = {
        "world": {},
        "normalized_params": {
            "list_url": "https://example.com/notices",
            "task_description": "采集公告",
            "fields": [{"name": "title", "description": "公告标题", "required": True}],
        },
    }

    params = select_request_params(state)

    assert params["list_url"] == "https://example.com/notices"
    assert params["task_description"] == "采集公告"


def test_chat_prepare_execution_handoff_normalizes_invalid_grouping_semantics() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "按学科分类采集专业列表",
        },
        "conversation": {
            "clarified_task": {
                "list_url": "https://example.com/majors",
                "task_description": "按学科分类采集专业列表",
                "fields": [{"name": "title", "description": "专业名称", "required": True}],
                "group_by": "none",
                "per_group_target_count": 10,
                "total_target_count": 0,
                "category_discovery_mode": "manual",
                "requested_categories": ["土木工程"],
                "category_examples": ["交通运输工程"],
            },
            "selected_skills": [],
        },
    }

    result = chat_prepare_execution_handoff(state)
    normalized = result["normalized_params"]

    assert normalized["group_by"] == "none"
    assert normalized["per_group_target_count"] is None
    assert normalized["total_target_count"] is None
    assert normalized["category_discovery_mode"] == "auto"
    assert normalized["requested_categories"] == []
    assert normalized["category_examples"] == []


@pytest.mark.asyncio
async def test_chat_clarify_uses_chat_context_start_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_run_context(run_id=None, trace_id="trace-chat-node-start")

    class _FakeRuntime:
        def __init__(self, _repository) -> None:
            return None

        def discover_by_url(self, _url: str) -> list[object]:
            return []

        async def get_or_select(self, **_kwargs) -> list[object]:
            return []

        def format_selected_skills_context(self, _bodies) -> str:
            return ""

        def load_selected_bodies(self, _items) -> list[str]:
            return []

    class _FakeClarifierAdapter:
        llm = object()

        async def clarify(self, history, **kwargs):
            assert len(history) == 1
            assert kwargs["available_skills"] == []
            return ClarificationResult(
                status="need_clarification",
                intent="collect notices",
                confidence=0.4,
                next_question="请提供列表页 URL。",
                reason="",
                task=None,
            )

    monkeypatch.setattr(entry_nodes_module, "SkillRuntime", _FakeRuntime)
    monkeypatch.setattr(entry_nodes_module, "TaskClarifierAdapter", _FakeClarifierAdapter)

    result = await chat_clarify({"cli_args": {"request": "采集公告"}})
    conversation = result["conversation"]

    assert result["node_status"] == "ok"
    assert conversation["flow_state"] == "needs_input"
    assert conversation["pending_question"] == "请提供列表页 URL。"
    assert conversation["chat_session_id"]
    assert conversation["chat_session"]["turns"][-1]["role"] == "assistant"
    clear_run_context()


@pytest.mark.asyncio
async def test_chat_clarify_uses_chat_context_advance_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_run_context(run_id=None, trace_id="trace-chat-node-advance")

    class _FakeRuntime:
        def __init__(self, _repository) -> None:
            return None

        def discover_by_url(self, _url: str) -> list[object]:
            return []

        async def get_or_select(self, **_kwargs) -> list[object]:
            return []

        def format_selected_skills_context(self, _bodies) -> str:
            return ""

        def load_selected_bodies(self, _items) -> list[str]:
            return []

    class _FakeClarifierAdapter:
        llm = object()

        async def clarify(self, history, **_kwargs):
            assert history[-1].content == "抓取标题和时间"
            return ClarificationResult(
                status="ready",
                intent="collect notices",
                confidence=0.9,
                next_question="",
                reason="",
                task=ClarifiedTask(
                    intent="collect notices",
                    list_url="https://example.com/notices",
                    task_description="采集公告",
                    fields=(RequestedField(name="title", description="标题"),),
                ),
            )

    monkeypatch.setattr(entry_nodes_module, "SkillRuntime", _FakeRuntime)
    monkeypatch.setattr(entry_nodes_module, "TaskClarifierAdapter", _FakeClarifierAdapter)

    session = ClarificationSession(
        session_id="session-1",
        turns=(
            DialogueMessage(role="user", content="采集公告"),
            DialogueMessage(role="assistant", content="请提供列表页 URL。"),
        ),
    )
    result = await chat_clarify(
        {
            "cli_args": {"request": "采集公告"},
            "conversation": {
                "chat_session_id": "session-1",
                "chat_session": session.to_payload(),
                "chat_history": [
                    {"role": "user", "content": "采集公告"},
                    {"role": "assistant", "content": "请提供列表页 URL。"},
                    {"role": "user", "content": "抓取标题和时间"},
                ],
            },
        }
    )
    conversation = result["conversation"]

    assert result["node_status"] == "ok"
    assert conversation["flow_state"] == "ready"
    assert conversation["clarified_task"]["list_url"] == "https://example.com/notices"
    assert conversation["chat_session"]["status"] == "finalized"
    clear_run_context()


@pytest.mark.asyncio
async def test_chat_review_task_override_normalizes_grouping_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        entry_nodes_module,
        "interrupt",
        lambda _payload: {
            "action": "override_task",
            "task": {
                "intent": "collect",
                "list_url": "https://example.com/majors",
                "task_description": "按学科分类采集专业列表",
                "fields": [{"name": "title", "description": "专业名称", "required": True}],
                "group_by": "category",
                "per_group_target_count": -1,
                "total_target_count": "0",
                "category_discovery_mode": "manual",
                "requested_categories": [],
                "category_examples": ["交通运输工程"],
            },
        },
    )
    state = {
        "cli_args": {"request": "按学科分类采集专业列表"},
        "conversation": {
            "clarified_task": {
                "list_url": "https://example.com/majors",
                "task_description": "按学科分类采集专业列表",
                "fields": [{"name": "title", "description": "专业名称", "required": True}],
            }
        },
    }

    result = await chat_review_task(state)
    task = result["conversation"]["clarified_task"]

    assert task["group_by"] == "category"
    assert task["per_group_target_count"] is None
    assert task["total_target_count"] is None
    assert task["category_discovery_mode"] == "auto"
    assert task["requested_categories"] == []
    assert task["category_examples"] == ["交通运输工程"]


@pytest.mark.asyncio
async def test_llm_history_rank_prompt_includes_semantic_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class _FakeLLM:
        model_name = "fake-ranker"

        def __init__(self, *args, **kwargs) -> None:
            return None

    async def _fake_ainvoke(_llm, messages):
        captured["prompt"] = str(messages[0].content)
        return {"ok": True}

    monkeypatch.setattr(entry_nodes_module, "ChatOpenAI", _FakeLLM)
    monkeypatch.setattr(entry_nodes_module, "ainvoke_with_stream", _fake_ainvoke)
    monkeypatch.setattr(entry_nodes_module, "extract_response_text_from_llm_payload", lambda _payload: "{}")
    monkeypatch.setattr(entry_nodes_module, "summarize_llm_payload", lambda _payload: {})
    monkeypatch.setattr(
        entry_nodes_module,
        "extract_json_dict_from_llm_payload",
        lambda _payload: {"ranked": [1]},
    )
    monkeypatch.setattr(entry_nodes_module, "append_llm_trace", lambda **_kwargs: None)

    ranked = await entry_nodes_module._llm_rank_history(
        "把专业按分类各抓 3 条",
        "semantic-sig-current",
        {
            "group_by": "category",
            "per_group_target_count": 3,
            "requested_categories": ["土木工程"],
        },
        [
            {
                "task_description": "按学科分类采集专业列表",
                "fields": ["title"],
                "collected_count": 12,
                "semantic_signature": "semantic-sig-001",
                "strategy_payload": {
                    "group_by": "category",
                    "per_group_target_count": 3,
                    "requested_categories": ["土木工程"],
                },
            }
        ],
    )

    assert ranked[0]["semantic_signature"] == "semantic-sig-001"
    assert "semantic-sig-001" in captured["prompt"]
    assert '"group_by": "category"' in captured["prompt"]


@pytest.mark.asyncio
async def test_chat_history_match_normalizes_stale_current_semantic_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeQueryService:
        def find_by_url(self, _url: str) -> list[dict[str, object]]:
            return [
                {
                    "registry_id": "registry-semantic-001",
                    "task_description": "按学科分类采集专业列表",
                    "fields": ["title"],
                    "collected_count": 12,
                    "semantic_signature": "semantic-sig-001",
                    "strategy_payload": {
                        "group_by": "category",
                        "per_group_target_count": 3,
                        "requested_categories": ["土木工程"],
                    },
                }
            ]

    monkeypatch.setattr(entry_nodes_module, "TaskRunQueryService", _FakeQueryService)

    async def _fake_rank_history(_current_desc, current_semantic_signature, current_strategy_payload, history):
        captured["semantic_signature"] = current_semantic_signature
        captured["strategy_payload"] = dict(current_strategy_payload)
        captured["history"] = history
        return []

    monkeypatch.setattr(entry_nodes_module, "_llm_rank_history", _fake_rank_history)

    task = {
        "list_url": "https://example.com/majors",
        "task_description": "按学科分类采集专业列表",
        "fields": [{"name": "title", "description": "专业名称", "required": True}],
        "group_by": "category",
        "per_group_target_count": 3,
        "category_discovery_mode": "manual",
        "requested_categories": ["土木工程"],
        "semantic_signature": "stale-semantic-signature",
    }
    expected_signature = build_semantic_signature(task)

    result = await chat_history_match(
        {
            "meta": {"thread_id": "thread-001"},
            "conversation": {"clarified_task": task},
        }
    )

    assert captured["semantic_signature"] == expected_signature
    assert captured["strategy_payload"] == {
        "group_by": "category",
        "per_group_target_count": 3,
        "total_target_count": None,
        "category_discovery_mode": "manual",
        "requested_categories": ["土木工程"],
        "category_examples": [],
        "field_names": ["title"],
    }
    assert result["history_match_done"] is True


@pytest.mark.asyncio
async def test_chat_history_match_preserves_current_task_description_when_reusing_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeQueryService:
        def find_by_url(self, _url: str) -> list[dict[str, object]]:
            return [
                {
                    "registry_id": "registry-semantic-001",
                    "task_description": "按学科分类采集专业列表",
                    "fields": ["title"],
                    "collected_count": 12,
                    "semantic_signature": "semantic-sig-001",
                    "strategy_payload": {
                        "group_by": "category",
                        "per_group_target_count": 3,
                        "total_target_count": None,
                        "category_discovery_mode": "manual",
                        "requested_categories": ["土木工程"],
                        "category_examples": ["土木工程"],
                    },
                }
            ]

    monkeypatch.setattr(entry_nodes_module, "TaskRunQueryService", _FakeQueryService)

    async def _fake_rank_history(_current_desc, _semantic_signature, _strategy_payload, history):
        return history

    monkeypatch.setattr(entry_nodes_module, "_llm_rank_history", _fake_rank_history)
    monkeypatch.setattr(entry_nodes_module, "interrupt", lambda _payload: {"choice": 1})

    state = {
        "meta": {"thread_id": "thread-001"},
        "conversation": {
            "clarified_task": {
                "list_url": "https://example.com/majors",
                "task_description": "把专业按分类各抓 3 条",
                "fields": [{"name": "title", "description": "专业名称", "required": True}],
                "group_by": "none",
            }
        },
    }

    result = await chat_history_match(state)
    task = result["conversation"]["clarified_task"]
    handoff = chat_prepare_execution_handoff(
        {
            "cli_args": {"output_dir": "output", "request": "把专业按分类各抓 3 条"},
            "conversation": {"clarified_task": task, "selected_skills": []},
        }
    )

    assert task["task_description"] == "把专业按分类各抓 3 条"
    assert task["matched_registry_id"] == "registry-semantic-001"
    assert task["semantic_signature"] == "semantic-sig-001"
    assert task["strategy_payload"]["group_by"] == "category"
    assert handoff["normalized_params"]["semantic_signature"] == build_semantic_signature(task)
    assert handoff["normalized_params"]["strategy_payload"]["group_by"] == "category"
    assert handoff["normalized_params"]["task_description"] == "把专业按分类各抓 3 条"
