from __future__ import annotations

import json

from autospider.common.storage.persistence import CollectionConfig, ConfigPersistence, ProgressPersistence
from autospider.common.types import SubTask, SubTaskStatus, TaskPlan
from autospider.graph.subgraphs.multi_dispatch import _build_dispatch_summary


def test_progress_persistence_append_urls_is_deterministic(tmp_path):
    persistence = ProgressPersistence(output_dir=tmp_path)

    persistence.append_urls(["https://example.com/b", "https://example.com/a", "https://example.com/b"])
    persistence.append_urls(["https://example.com/c", "https://example.com/a"])

    content = (tmp_path / "urls.txt").read_text(encoding="utf-8")
    assert content == "https://example.com/a\nhttps://example.com/b\nhttps://example.com/c\n"

    persistence.append_urls(["https://example.com/c"])
    assert (tmp_path / "urls.txt").read_text(encoding="utf-8") == content


def test_config_persistence_save_does_not_inject_timestamps(tmp_path):
    persistence = ConfigPersistence(config_dir=tmp_path)
    config = CollectionConfig(
        list_url="https://example.com/list",
        task_description="采集列表",
        nav_steps=[{"action": "click", "target": "招标公告"}],
    )

    persistence.save(config)
    first = json.loads((tmp_path / "collection_config.json").read_text(encoding="utf-8"))
    persistence.save(config)
    second = json.loads((tmp_path / "collection_config.json").read_text(encoding="utf-8"))

    assert first == second
    assert first["created_at"] == ""
    assert first["updated_at"] == ""


def test_build_dispatch_summary_keeps_plan_timestamp_stable():
    plan = TaskPlan(
        plan_id="plan_01",
        original_request="采集项目",
        site_url="https://example.com",
        created_at="fixed-ts",
        updated_at="fixed-ts",
        subtasks=[
            SubTask(
                id="sub_01",
                name="子任务",
                list_url="https://example.com/list",
                task_description="采集子任务",
                status=SubTaskStatus.PENDING,
            )
        ],
        total_subtasks=1,
    )
    result_item = {
        "id": "sub_01",
        "status": SubTaskStatus.COMPLETED.value,
        "error": "",
        "result_file": "output/pipeline_extracted_items.jsonl",
        "collected_count": 3,
    }

    first = _build_dispatch_summary(plan, [result_item])
    second = _build_dispatch_summary(plan, [result_item])

    assert first == second
    assert plan.updated_at == "fixed-ts"
