from __future__ import annotations

from autospider.graph.execution_handoff import (
    build_chat_execution_params,
    build_chat_review_payload,
)
from autospider.graph.nodes.entry_nodes import chat_prepare_execution_handoff


def _task_payload() -> dict[str, object]:
    return {
        "intent": "抓取商品列表",
        "list_url": "https://example.com/list",
        "task_description": "抓取标题和价格",
        "fields": [
            {
                "name": "title",
                "description": "商品标题",
                "required": True,
                "data_type": "text",
                "example": "示例标题",
            }
        ],
        "max_pages": 3,
        "target_url_count": 20,
        "consumer_concurrency": 2,
        "field_explore_count": 2,
        "field_validate_count": 2,
    }


def test_review_payload_and_execution_params_share_runtime_controls() -> None:
    task = _task_payload()
    cli_args = {
        "pipeline_mode": "memory",
        "output_dir": "output/custom",
        "headless": True,
        "request": "抓取商品",
        "consumer_concurrency": 5,
        "max_concurrent": 7,
        "global_browser_budget": 9,
    }
    selected_skills = [
        {
            "name": "shop",
            "description": "shop extractor",
            "path": "skills/shop.md",
            "domain": "example.com",
        }
    ]

    review_payload = build_chat_review_payload(
        thread_id="thread-1",
        cli_args=cli_args,
        task=task,
        dispatch_mode="multi",
    )
    params = build_chat_execution_params(
        cli_args=cli_args,
        task=task,
        dispatch_mode="multi",
        selected_skills=selected_skills,
    )

    assert review_payload["type"] == "chat_review"
    assert review_payload["thread_id"] == "thread-1"
    assert review_payload["clarified_task"] == task
    assert review_payload["effective_options"] == {
        "max_pages": 3,
        "target_url_count": 20,
        "consumer_concurrency": 5,
        "field_explore_count": 2,
        "field_validate_count": 2,
        "pipeline_mode": "redis",
        "execution_mode": "multi",
        "headless": True,
        "output_dir": "output/custom",
        "serial_mode": False,
        "max_concurrent": 7,
        "global_browser_budget": 9,
    }
    assert params["pipeline_mode"] == "redis"
    assert params["execution_mode_resolved"] == "multi"
    assert params["consumer_concurrency"] == review_payload["effective_options"]["consumer_concurrency"]
    assert params["max_concurrent"] == review_payload["effective_options"]["max_concurrent"]
    assert params["global_browser_budget"] == review_payload["effective_options"]["global_browser_budget"]
    assert params["selected_skills"] == selected_skills


def test_serial_mode_forces_single_worker_and_browser_budget() -> None:
    task = _task_payload()
    cli_args = {
        "serial_mode": "true",
        "consumer_concurrency": 5,
        "max_concurrent": 7,
        "global_browser_budget": 9,
    }

    review_payload = build_chat_review_payload(
        thread_id="thread-1",
        cli_args=cli_args,
        task=task,
        dispatch_mode="multi",
    )
    params = build_chat_execution_params(
        cli_args=cli_args,
        task=task,
        dispatch_mode="multi",
        selected_skills=[],
    )

    assert review_payload["effective_options"]["serial_mode"] is True
    assert review_payload["effective_options"]["consumer_concurrency"] == 1
    assert review_payload["effective_options"]["max_concurrent"] == 1
    assert review_payload["effective_options"]["global_browser_budget"] == 1
    assert params["serial_mode"] is True
    assert params["consumer_concurrency"] == 1
    assert params["max_concurrent"] == 1
    assert params["global_browser_budget"] == 1


def test_entry_node_handoff_writes_normalized_params_to_conversation_state() -> None:
    task = _task_payload()
    state = {
        "cli_args": {
            "pipeline_mode": "memory",
            "output_dir": "output/custom",
            "headless": True,
            "request": "抓取商品",
        },
        "conversation": {
            "clarified_task": task,
            "selected_skills": [
                {
                    "name": "shop",
                    "description": "shop extractor",
                    "path": "skills/shop.md",
                    "domain": "example.com",
                }
            ],
        },
    }

    result = chat_prepare_execution_handoff(state)

    assert result["node_status"] == "ok"
    assert result["normalized_params"]["pipeline_mode"] == "redis"
    assert result["normalized_params"]["selected_skills"] == state["conversation"]["selected_skills"]
    assert result["conversation"]["normalized_params"] == result["normalized_params"]
