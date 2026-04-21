from __future__ import annotations

from autospider.composition.pipeline import runner as legacy_runner
from autospider.composition.pipeline import runner as active_runner


def test_active_runner_classification_wrapper_accepts_failure_metadata() -> None:
    result = active_runner._classify_pipeline_result(
        total_urls=1,
        success_count=0,
        state_error="producer_error",
        validation_failures=[],
        terminal_reason="producer_error",
        failure_category="site_defense",
        failure_detail="captcha detected",
    )

    assert result["failure_category"] == "site_defense"
    assert result["failure_detail"] == "captcha detected"
    assert result["outcome_state"] == "system_failure"


def test_legacy_runner_classification_wrapper_accepts_failure_metadata() -> None:
    result = legacy_runner._classify_pipeline_result(
        total_urls=1,
        success_count=0,
        state_error="producer_error",
        validation_failures=[],
        terminal_reason="producer_error",
        failure_category="site_defense",
        failure_detail="captcha detected",
    )

    assert result["failure_category"] == "site_defense"
    assert result["failure_detail"] == "captcha detected"
    assert result["outcome_state"] == "system_failure"

