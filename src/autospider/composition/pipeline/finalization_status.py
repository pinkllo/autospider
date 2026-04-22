"""Pipeline result classification helpers."""

from __future__ import annotations

from typing import Any, Callable

EXECUTION_STATE_COMPLETED = "completed"
EXECUTION_STATE_FAILED = "failed"
EXECUTION_STATE_INTERRUPTED = "interrupted"
OUTCOME_STATE_SUCCESS = "success"
OUTCOME_STATE_PARTIAL_SUCCESS = "partial_success"
OUTCOME_STATE_NO_DATA = "no_data"
OUTCOME_STATE_SYSTEM_FAILURE = "system_failure"
OUTCOME_STATE_INTERRUPTED = "interrupted"
DURABILITY_STATE_STAGED = "staged"
DURABILITY_STATE_DURABLE = "durable"
DURABILITY_STATE_FAILED_COMMIT = "failed_commit"


def classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
    terminal_reason: str = "",
    failure_category: str = "",
    failure_detail: str = "",
) -> dict[str, object]:
    failed_count = max(total_urls - success_count, 0)
    success_rate = (success_count / total_urls) if total_urls > 0 else 0.0
    validation_failure_count = len(validation_failures)
    normalized_reason = str(terminal_reason or "").strip()
    normalized_failure_category = str(failure_category or "").strip()
    normalized_failure_detail = str(failure_detail or "").strip()

    if normalized_reason == "browser_intervention":
        execution_state = EXECUTION_STATE_INTERRUPTED
        outcome_state = OUTCOME_STATE_INTERRUPTED
    elif state_error:
        execution_state = EXECUTION_STATE_FAILED
        outcome_state = OUTCOME_STATE_SYSTEM_FAILURE
        normalized_reason = normalized_reason or str(state_error)
    elif total_urls <= 0:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_NO_DATA
        normalized_reason = normalized_reason or "no_data_collected"
    elif failed_count <= 0 and validation_failure_count == 0:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_SUCCESS
    else:
        execution_state = EXECUTION_STATE_COMPLETED
        outcome_state = OUTCOME_STATE_PARTIAL_SUCCESS
        normalized_reason = normalized_reason or "partial_data_available"

    if outcome_state == OUTCOME_STATE_SUCCESS:
        promotion_state = "reusable"
    elif outcome_state == OUTCOME_STATE_INTERRUPTED:
        promotion_state = "rejected"
    elif success_count > 0:
        promotion_state = "diagnostic_only"
    else:
        promotion_state = "rejected"

    if not normalized_failure_category and outcome_state in {
        OUTCOME_STATE_SYSTEM_FAILURE,
        OUTCOME_STATE_INTERRUPTED,
    }:
        normalized_failure_detail = normalized_failure_detail or normalized_reason

    return {
        "execution_state": execution_state,
        "outcome_state": outcome_state,
        "terminal_reason": normalized_reason,
        "promotion_state": promotion_state,
        "success_rate": round(success_rate, 4),
        "failed_count": failed_count,
        "required_field_success_rate": round(success_rate, 4),
        "validation_failure_count": validation_failure_count,
        "failure_category": normalized_failure_category,
        "failure_detail": normalized_failure_detail,
    }


def resolve_pipeline_error(*, state_error: object, summary: dict[str, Any]) -> str | None:
    state_message = str(state_error or "").strip()
    if state_message:
        return state_message
    summary_message = str(summary.get("error") or "").strip()
    return summary_message or None


def should_promote_skill(
    *,
    state_error: object,
    summary: dict[str, Any],
    validation_failures: list[dict[str, Any]],
) -> bool:
    effective_error = resolve_pipeline_error(state_error=state_error, summary=summary)
    if (
        not effective_error
        and str(summary.get("promotion_state") or "").strip().lower() == "reusable"
    ):
        return True

    classified = classify_pipeline_result(
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        state_error=effective_error,
        validation_failures=validation_failures,
        terminal_reason=str(summary.get("terminal_reason") or ""),
    )
    return bool(classified.get("promotion_state") == "reusable")


def refresh_summary_classification(
    *,
    classifier: Callable[..., dict[str, object]],
    summary: dict[str, Any],
    state_error: object,
    validation_failures: list[dict[str, Any]],
    failure_category: str = "",
    failure_detail: str = "",
) -> None:
    summary.update(
        classifier(
            total_urls=int(summary.get("total_urls", 0) or 0),
            success_count=int(summary.get("success_count", 0) or 0),
            state_error=resolve_pipeline_error(state_error=state_error, summary=summary),
            validation_failures=validation_failures,
            terminal_reason=str(summary.get("terminal_reason") or ""),
            failure_category=str(failure_category or summary.get("failure_category") or ""),
            failure_detail=str(failure_detail or summary.get("failure_detail") or ""),
        )
    )
