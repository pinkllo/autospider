from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.platform.llm.decider import LLMDecider
from autospider.legacy.common.protocol import (
    parse_protocol_message,
    parse_protocol_message_diagnostics,
)
from autospider.platform.shared_kernel.types import ActionType
from autospider.contexts.planning.domain import (
    classify_protocol_violation,
    classify_runtime_exception,
)
from autospider.legacy.graph.nodes import capability_nodes
from autospider.legacy.graph.recovery import build_recovery_directive


class StateMismatchError(RuntimeError):
    pass


class RuleStaleError(RuntimeError):
    pass


class SiteDefenseError(RuntimeError):
    pass


class FatalCapabilityError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_plan_request_fails_fast_when_list_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        def __init__(self, **_kwargs) -> None:
            self.page = object()

        @staticmethod
        def build_options(_request):
            return {}

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class _UnexpectedPlanner:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("TaskPlanner should not be constructed when list_url is empty")

    monkeypatch.setattr(capability_nodes, "BrowserRuntimeSession", _FakeSession)
    monkeypatch.setattr(capability_nodes, "TaskPlanner", _UnexpectedPlanner)

    request = capability_nodes.build_execution_request(
        {"list_url": "", "task_description": "采集公告", "fields": []},
        thread_id="thread-001",
    )

    with pytest.raises(RuntimeError, match="missing_list_url"):
        await capability_nodes._plan_request(request)


def test_parse_protocol_message_diagnostics_returns_validation_errors() -> None:
    diagnostics = parse_protocol_message_diagnostics({"action": "click", "args": {}})

    assert diagnostics["message"] is None
    assert diagnostics["action"] == "click"
    assert any(
        "click requires target_text or mark_id" in item for item in diagnostics["validation_errors"]
    )
    assert parse_protocol_message({"action": "click", "args": {}}) is None


def test_classify_protocol_violation_keeps_validation_details() -> None:
    diagnostics = parse_protocol_message_diagnostics({"action": "click", "args": {}})

    failure = classify_protocol_violation(
        component="decider",
        diagnostics=diagnostics,
        page_id="entry",
    )

    assert failure["page_id"] == "entry"
    assert failure["category"] == "contract_violation"
    assert failure["detail"] == "invalid_protocol_message"
    assert failure["metadata"]["component"] == "decider"
    assert failure["metadata"]["validation_errors"] == diagnostics["validation_errors"]


def test_classify_runtime_exception_returns_failure_record() -> None:
    failure = classify_runtime_exception(
        component="collect_urls_node",
        error=TimeoutError("timed out"),
        page_id="list-page",
    )

    assert failure["page_id"] == "list-page"
    assert failure["category"] == "transient"
    assert failure["detail"] == "timeout_error"
    assert failure["metadata"]["component"] == "collect_urls_node"
    assert failure["metadata"]["exception_type"] == "TimeoutError"
    assert failure["metadata"]["message"] == "timed out"


def test_classify_runtime_exception_marks_unknown_runtime_error_as_fatal() -> None:
    failure = classify_runtime_exception(
        component="collect_urls_node",
        error=RuntimeError("boom"),
        page_id="list-page",
    )

    assert failure["page_id"] == "list-page"
    assert failure["category"] == "fatal"
    assert failure["detail"] == "runtime_error"
    assert failure["metadata"]["message"] == "boom"


def test_decider_exposes_contract_violation_via_action_contract() -> None:
    decider = object.__new__(LLMDecider)
    decider.last_failure_record = None

    action = decider._parse_response({"action": "click", "args": {}})

    assert action.action == ActionType.RETRY
    assert action.failure_record is not None
    assert action.failure_record["category"] == "contract_violation"
    assert "contract_violation" in action.thinking


@pytest.mark.parametrize(
    ("category", "expected_action"),
    [
        ("transient", "retry"),
        ("contract_violation", "reask"),
        ("state_mismatch", "replan"),
        ("rule_stale", "replan"),
        ("site_defense", "human_intervention"),
        ("fatal", "fail"),
    ],
)
def test_build_recovery_directive_maps_category_to_action(
    category: str,
    expected_action: str,
) -> None:
    directive = build_recovery_directive(
        failure_record={"category": category, "detail": "example"},
        failure_count=0,
        max_retries=2,
    )

    assert directive.action == expected_action


def test_build_recovery_directive_fails_after_retry_budget_for_transient_failure() -> None:
    directive = build_recovery_directive(
        failure_record={"category": "transient", "detail": "timeout_error"},
        failure_count=2,
        max_retries=2,
    )

    assert directive.action == "fail"
    assert directive.reason == "retry_budget_exhausted"


def test_build_recovery_directive_fails_for_unknown_category() -> None:
    directive = build_recovery_directive(
        failure_record={"category": "mystery", "detail": "boom"},
        failure_count=0,
        max_retries=2,
    )

    assert directive.action == "fail"
    assert directive.reason == "unknown_failure_category"


@pytest.mark.asyncio
async def test_capability_recovery_retries_transient_exception_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def runner() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("timed out")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(capability_nodes.asyncio, "sleep", no_sleep)

    state = {
        "world": {
            "request_params": {
                "decision_context": {"recovery_policy": {"max_retries": 1}},
            }
        }
    }

    result = await capability_nodes._execute_with_recovery(
        state,
        runner,
        error_code="collect_urls_failed",
        node_name="collect_urls_node",
    )

    assert attempts == 2
    assert result["node_status"] == "fatal"
    assert result["node_error"]["code"] == "collect_urls_failed"
    assert result["failure_records"][0]["category"] == "transient"
    assert result["failure_records"][0]["detail"] == "timeout_error"


@pytest.mark.parametrize(
    ("error_factory", "expected_category", "expected_directive", "expected_attempts"),
    [
        (lambda: StateMismatchError("dom changed"), "state_mismatch", "replan", 1),
        (lambda: RuleStaleError("selector stale"), "rule_stale", "replan", 1),
        (lambda: SiteDefenseError("captcha required"), "site_defense", "human_intervention", 1),
        (lambda: FatalCapabilityError("schema corrupted"), "fatal", "fail", 1),
    ],
)
@pytest.mark.asyncio
async def test_capability_recovery_escalates_non_retry_categories(
    monkeypatch: pytest.MonkeyPatch,
    error_factory,
    expected_category: str,
    expected_directive: str,
    expected_attempts: int,
) -> None:
    attempts = 0

    async def runner() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise error_factory()

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(capability_nodes.asyncio, "sleep", no_sleep)

    state = {
        "world": {
            "request_params": {
                "decision_context": {"recovery_policy": {"max_retries": 3}},
            }
        }
    }

    result = await capability_nodes._execute_with_recovery(
        state,
        runner,
        error_code="collect_urls_failed",
        node_name="collect_urls_node",
    )

    assert attempts == expected_attempts
    assert result["node_status"] == "fatal"
    assert result["recovery_directive"]["action"] == expected_directive
    assert result["failure_records"][0]["category"] == expected_category


def test_capability_recovery_exposes_directive_for_unknown_runtime_error() -> None:
    failure_record = classify_runtime_exception(
        component="collect_urls_node",
        error=RuntimeError("boom"),
    )

    directive = build_recovery_directive(
        failure_record=failure_record,
        failure_count=0,
        max_retries=2,
    )

    assert failure_record["category"] == "fatal"
    assert directive.action == "fail"
