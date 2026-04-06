from __future__ import annotations

from autospider.graph.nodes.entry_nodes import chat_prepare_execution_handoff, normalize_pipeline_params


def test_chat_prepare_execution_handoff_only_forwards_runtime_subtask_params_that_are_consumed():
    result = chat_prepare_execution_handoff(
        {
            "cli_args": {
                "request": "抓取公告",
                "runtime_subtasks": True,
                "runtime_subtask_max_depth": 4,
                "runtime_subtask_max_children": 6,
                "runtime_subtasks_use_main_model": False,
            },
            "selected_skills": [
                {
                    "name": "notice-skill",
                    "description": "公告采集技能",
                    "path": "d:/autospider/.agents/skills/example.com/SKILL.md",
                    "domain": "example.com",
                }
            ],
            "clarified_task": {
                "list_url": "https://example.com/list",
                "task_description": "抓取公告详情",
                "fields": [{"name": "title", "description": "标题"}],
            },
        }
    )

    assert result["node_status"] == "ok"
    normalized = result["normalized_params"]
    assert "runtime_subtasks" not in normalized
    assert "runtime_subtask_max_depth" not in normalized
    assert normalized["runtime_subtask_max_children"] == 6
    assert normalized["runtime_subtasks_use_main_model"] is False
    assert normalized["selected_skills"][0]["name"] == "notice-skill"


def test_chat_prepare_execution_handoff_forces_serial_mode_when_enabled():
    result = chat_prepare_execution_handoff(
        {
            "cli_args": {
                "request": "抓取公告",
                "serial_mode": True,
                "consumer_concurrency": 4,
                "max_concurrent": 3,
            },
            "clarified_task": {
                "list_url": "https://example.com/list",
                "task_description": "抓取公告详情",
                "fields": [{"name": "title", "description": "标题"}],
                "consumer_concurrency": 5,
            },
        }
    )

    normalized = result["normalized_params"]
    assert normalized["serial_mode"] is True
    assert normalized["consumer_concurrency"] == 1
    assert normalized["max_concurrent"] == 1


def test_normalize_pipeline_params_forces_serial_mode_when_enabled():
    result = normalize_pipeline_params(
        {
            "cli_args": {
                "list_url": "https://example.com/list",
                "task_description": "抓取公告详情",
                "serial_mode": True,
                "consumer_concurrency": 6,
                "max_concurrent": 2,
            }
        }
    )

    normalized = result["normalized_params"]
    assert normalized["serial_mode"] is True
    assert normalized["consumer_concurrency"] == 1
    assert normalized["max_concurrent"] == 1
