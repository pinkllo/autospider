from __future__ import annotations

import pytest
from typer.testing import CliRunner

from autospider import cli
from autospider.graph.execution_handoff import build_chat_review_payload
from autospider.graph.nodes.entry_nodes import chat_prepare_execution_handoff

pytestmark = pytest.mark.smoke


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


def test_chat_pipeline_help_does_not_expose_mode_option() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["chat-pipeline", "--help"])

    assert result.exit_code == 0
    assert "--mode" not in result.stdout


def test_chat_pipeline_rejects_mode_option() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["chat-pipeline", "--mode", "memory", "--request", "抓取商品"])

    assert result.exit_code != 0
    assert "No such option: --mode" in result.output


def test_chat_pipeline_review_and_handoff_force_redis_mode() -> None:
    task = _task_payload()
    state = {
        "thread_id": "thread-1",
        "cli_args": {
            "pipeline_mode": "memory",
            "output_dir": "output/custom",
            "headless": True,
            "request": "抓取商品",
        },
        "conversation": {"clarified_task": task},
    }

    review_payload = build_chat_review_payload(
        thread_id="thread-1",
        cli_args=state["cli_args"],
        task=task,
        dispatch_mode="multi",
    )
    handoff_result = chat_prepare_execution_handoff(state)

    assert review_payload["effective_options"]["pipeline_mode"] == "redis"
    assert handoff_result["normalized_params"]["pipeline_mode"] == "redis"
