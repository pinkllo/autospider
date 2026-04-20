from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.composition.legacy.taskplane.protocol import ResultStatus, TaskResult
from autospider.composition.legacy.taskplane_adapter.result_bridge import ResultBridge


def _sample_runtime_state() -> SubTaskRuntimeState:
    return SubTaskRuntimeState(
        subtask_id="s1",
        name="招标公告",
        status="completed",
        outcome_type="success",
        collected_count=42,
        result_file="output/items.jsonl",
    )


class TestResultBridge:
    def test_to_result_success(self) -> None:
        result = ResultBridge.to_result(_sample_runtime_state())

        assert result.ticket_id == "s1"
        assert result.status == ResultStatus.SUCCESS
        assert result.output["collected_count"] == 42

    def test_to_result_failed(self) -> None:
        state = SubTaskRuntimeState(
            subtask_id="s1",
            status="system_failure",
            outcome_type="system_failure",
            error="timeout",
        )

        result = ResultBridge.to_result(state)
        assert result.status == ResultStatus.FAILED
        assert result.error == "timeout"

    def test_to_result_expanded(self) -> None:
        state = SubTaskRuntimeState(
            subtask_id="s1",
            status="expanded",
            outcome_type="expanded",
            expand_request={"spawned_subtasks": [{"id": "child1"}]},
        )

        result = ResultBridge.to_result(state)
        assert result.status == ResultStatus.EXPANDED

    def test_from_result(self) -> None:
        state = ResultBridge.from_result(
            TaskResult(
                result_id="r1",
                ticket_id="s1",
                status=ResultStatus.SUCCESS,
                output={
                    "subtask_id": "s1",
                    "name": "test",
                    "status": "completed",
                    "collected_count": 10,
                },
            )
        )

        assert state.subtask_id == "s1"
