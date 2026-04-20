from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from . import contract_tmp_dir, directory_files, run_contract_pipeline

SUMMARY_SCHEMA = {
    "type": "object",
    "required": [
        "run_id",
        "execution_id",
        "list_url",
        "task_description",
        "mode",
        "total_urls",
        "success_count",
        "failed_count",
        "items_file",
        "summary_file",
        "execution_state",
        "outcome_state",
        "promotion_state",
        "durability_state",
        "durably_persisted",
    ],
    "properties": {
        "run_id": {"type": "string"},
        "execution_id": {"type": "string"},
        "list_url": {"type": "string"},
        "task_description": {"type": "string"},
        "mode": {"type": "string"},
        "total_urls": {"type": "integer"},
        "success_count": {"type": "integer"},
        "failed_count": {"type": "integer"},
        "items_file": {"type": "string"},
        "summary_file": {"type": "string"},
        "execution_state": {"type": "string"},
        "outcome_state": {"type": "string"},
        "promotion_state": {"type": "string"},
        "durability_state": {"type": "string"},
        "durably_persisted": {"type": "boolean"},
    },
}

TASK_PLAN_SCHEMA = {
    "type": "object",
    "required": ["plan_id", "site_url", "original_request", "total_subtasks", "subtasks"],
    "properties": {
        "plan_id": {"type": "string"},
        "site_url": {"type": "string"},
        "original_request": {"type": "string"},
        "total_subtasks": {"type": "integer"},
        "subtasks": {"type": "array"},
    },
}

ITEM_SCHEMA = {
    "type": "object",
    "required": ["url", "title"],
    "properties": {"url": {"type": "string"}, "title": {"type": "string"}},
}


def test_output_layout_and_json_schema_match_contract_snapshot() -> None:
    with contract_tmp_dir() as tmp_path:
        artifacts = run_contract_pipeline(tmp_path)
        output_dir = artifacts.output_dir

        assert directory_files(output_dir) == [
            "pipeline_extracted_items.jsonl",
            "pipeline_summary.json",
            "plan_knowledge.md",
            "task_plan.json",
        ]
        validate(instance=_load_json(output_dir / "pipeline_summary.json"), schema=SUMMARY_SCHEMA)
        validate(instance=_load_json(output_dir / "task_plan.json"), schema=TASK_PLAN_SCHEMA)

        items = _load_json_lines(output_dir / "pipeline_extracted_items.jsonl")
        assert len(items) == 1
        validate(instance=items[0], schema=ITEM_SCHEMA)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_lines(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
