from __future__ import annotations

from autospider.graph.nodes.entry_nodes import chat_prepare_execution_handoff


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
