from __future__ import annotations

from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.legacy.taskplane_adapter.result_bridge import ResultBridge

from . import contract_tmp_dir, run_contract_pipeline, snapshot_shape


def test_current_result_envelopes_match_contract_snapshots() -> None:
    with contract_tmp_dir() as tmp_path:
        artifacts = run_contract_pipeline(tmp_path)
        runtime_state = SubTaskRuntimeState(
            subtask_id="contract-subtask-001",
            name="contract-detail",
            list_url=artifacts.page_url,
            status="completed",
            outcome_type="success",
            result_file=str(artifacts.output_dir / "pipeline_extracted_items.jsonl"),
            collected_count=1,
            summary=artifacts.result.summary.model_dump(mode="python"),
        )
        snapshot = {
            "pipeline_run_result": snapshot_shape(artifacts.result.to_payload()),
            "task_result": snapshot_shape(
                ResultBridge.to_result(runtime_state).model_dump(mode="python")
            ),
        }

        assert snapshot == {
            "pipeline_run_result": {
                "anchor_url": "str",
                "collected_urls": "int",
                "collection_config": {
                    "anchor_url": "str",
                    "common_detail_xpath": "str",
                    "jump_widget_xpath": "NoneType",
                    "list_url": "str",
                    "nav_steps": [{"action": "str", "url": "str"}],
                    "page_state_signature": "str",
                    "pagination_xpath": "NoneType",
                    "task_description": "str",
                    "variant_label": "str",
                },
                "committed_records": [{"success": "bool", "url": "str"}],
                "consumer_concurrency": "int",
                "durability_state": "str",
                "durably_persisted": "bool",
                "error": "str",
                "execution_id": "str",
                "execution_state": "str",
                "extraction_config": {
                    "fields": [
                        {
                            "data_type": "str",
                            "description": "str",
                            "example": "NoneType",
                            "extraction_source": "NoneType",
                            "fixed_value": "NoneType",
                            "name": "str",
                            "required": "bool",
                            "xpath_fallbacks": [],
                        }
                    ]
                },
                "extraction_evidence": [
                    {
                        "extraction_config": {
                            "fields": [
                                {
                                    "data_type": "str",
                                    "description": "str",
                                    "example": "NoneType",
                                    "extraction_source": "NoneType",
                                    "fixed_value": "NoneType",
                                    "name": "str",
                                    "required": "bool",
                                }
                            ]
                        },
                        "success": "bool",
                        "url": "str",
                    }
                ],
                "failed_count": "int",
                "failure_category": "str",
                "failure_detail": "str",
                "items_file": "str",
                "list_url": "str",
                "mode": "str",
                "outcome_state": "str",
                "page_state_signature": "str",
                "promotion_state": "str",
                "required_field_success_rate": "float",
                "run_id": "str",
                "skill_path": "str",
                "skill_state": "str",
                "success_count": "int",
                "success_rate": "float",
                "summary_file": "str",
                "target_url_count": "int",
                "task_description": "str",
                "terminal_reason": "str",
                "total_urls": "int",
                "validation_failure_count": "int",
                "validation_failures": [],
                "variant_label": "str",
            },
            "task_result": {
                "artifacts": [{"label": "str", "path": "str"}],
                "completed_at": "datetime",
                "error": "str",
                "output": {
                    "anchor_url": "str",
                    "collected_count": "int",
                    "collection_config": {},
                    "context": {},
                    "depth": "int",
                    "error": "str",
                    "execution_brief": {},
                    "expand_request": {},
                    "extraction_config": {},
                    "extraction_evidence": [],
                    "journal_entries": [],
                    "list_url": "str",
                    "mode": "str",
                    "name": "str",
                    "outcome_type": "str",
                    "page_state_signature": "str",
                    "parent_id": "str",
                    "result_file": "str",
                    "retry_count": "int",
                    "status": "str",
                    "subtask_id": "str",
                    "summary": {
                        "durability_state": "str",
                        "durably_persisted": "bool",
                        "execution_id": "str",
                        "execution_state": "str",
                        "failed_count": "int",
                        "failure_category": "str",
                        "failure_detail": "str",
                        "items_file": "str",
                        "outcome_state": "str",
                        "promotion_state": "str",
                        "reliable_for_aggregation": "bool",
                        "required_field_success_rate": "float",
                        "success_count": "int",
                        "success_rate": "float",
                        "terminal_reason": "str",
                        "total_urls": "int",
                        "validation_failure_count": "int",
                    },
                    "task_description": "str",
                    "validation_failures": [],
                    "variant_label": "str",
                },
                "result_id": "str",
                "spawned_tickets": [],
                "status": "ResultStatus",
                "ticket_id": "str",
            },
        }
