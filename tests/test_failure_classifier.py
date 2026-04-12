from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.common.llm.decider import LLMDecider
from autospider.common.protocol import (
    parse_protocol_message,
    parse_protocol_message_diagnostics,
)
from autospider.common.types import ActionType
from autospider.graph.failures import (
    classify_protocol_violation,
    classify_runtime_exception,
)
from autospider.graph.nodes import capability_nodes
from autospider.graph.recovery import build_recovery_directive


def test_parse_protocol_message_diagnostics_returns_validation_errors() -> None:
    diagnostics = parse_protocol_message_diagnostics({"action": "click", "args": {}})

    assert diagnostics["message"] is None
    assert diagnostics["action"] == "click"
    assert any("click requires target_text or mark_id" in item for item in diagnostics["validation_errors"])
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
    assert failure["category"] == "system_failure"
    assert failure["detail"] == "timeout_error"
    assert failure["metadata"]["component"] == "collect_urls_node"
    assert failure["metadata"]["exception_type"] == "TimeoutError"
    assert failure["metadata"]["message"] == "timed out"


def test_decider_exposes_contract_violation_failure_record() -> None:
    decider = object.__new__(LLMDecider)
    decider.last_failure_record = None

    action = decider._parse_response({"action": "click", "args": {}})

    assert action.action == ActionType.RETRY
    assert decider.last_failure_record is not None
    assert decider.last_failure_record["category"] == "contract_violation"
    assert "contract_violation" in action.thinking


def test_build_recovery_directive_fails_fast_for_contract_violations() -> None:
    directive = build_recovery_directive(
        failure_record={"category": "contract_violation", "detail": "invalid_protocol_message"},
        failure_count=0,
        max_retries=2,
    )

    assert directive.action == "fail"
    assert directive.delay_seconds == 0.0


@pytest.mark.asyncio
async def test_capability_recovery_retries_runtime_exception_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def runner() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("boom")

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
    assert result["failure_records"][0]["category"] == "system_failure"
    assert result["failure_records"][0]["detail"] == "runtime_error"
