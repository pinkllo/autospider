from __future__ import annotations

from tests.cli_test_support import fresh_import_cli

from autospider.legacy.graph.execution_handoff import build_chat_execution_params
from autospider.legacy.pipeline.types import ExecutionRequest


def test_cli_help_exposes_only_current_public_commands() -> None:
    cli = fresh_import_cli()
    command_names = {command.name for command in cli.app.registered_commands}

    assert "chat-pipeline" in command_names
    assert "db-init" in command_names
    assert "resume" in command_names
    assert "multi-pipeline" not in command_names


def test_cli_originated_grouped_handoff_preserves_category_semantics() -> None:
    state = {
        "cli_args": {
            "request": "帮我采集 example.com 上所有分类下的专业列表，每个分类抓 3 条",
            "output_dir": "output",
            "pipeline_mode": "redis",
            "max_concurrent": 4,
        },
        "conversation": {
            "selected_skills": [],
        },
    }
    task = {
        "intent": "collect",
        "list_url": "https://example.com/majors",
        "task_description": "采集页面上发现的所有分类下的专业列表，每个分类抓 3 条",
        "fields": [
            {"name": "title", "description": "专业名称", "required": True},
            {"name": "category_name", "description": "所属分类", "required": True},
        ],
        "group_by": "category",
        "per_group_target_count": 3,
        "total_target_count": None,
        "category_discovery_mode": "auto",
        "requested_categories": [],
        "category_examples": ["交通运输工程", "土木工程"],
    }

    params = build_chat_execution_params(state=state, task=task, dispatch_mode="multi")
    request = ExecutionRequest.from_params(params, thread_id="thread-001")

    assert params["request"] == state["cli_args"]["request"]
    assert params["group_by"] == "category"
    assert params["per_group_target_count"] == 3
    assert params["category_discovery_mode"] == "auto"
    assert params["requested_categories"] == []
    assert params["category_examples"] == ["交通运输工程", "土木工程"]
    assert request.group_by == "category"
    assert request.per_group_target_count == 3
    assert request.category_discovery_mode == "auto"
    assert request.requested_categories == []
    assert request.category_examples == ["交通运输工程", "土木工程"]
    assert request.pipeline_mode.value == "redis"
