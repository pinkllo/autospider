from __future__ import annotations

from autospider.composition.sagas.recovery_saga import RecoverySaga
from autospider.contexts.planning import SITE_DEFENSE_CATEGORY, TRANSIENT_CATEGORY


def test_recovery_saga_returns_retry_for_transient_failure() -> None:
    resolution = RecoverySaga().decide(
        failure_record={"category": TRANSIENT_CATEGORY},
        failure_count=0,
        max_retries=2,
    )

    assert resolution.action == "retry"
    assert resolution.delay_seconds >= 0


def test_recovery_saga_returns_human_intervention_for_site_defense() -> None:
    resolution = RecoverySaga().decide(
        failure_record={"category": SITE_DEFENSE_CATEGORY},
        failure_count=0,
        max_retries=2,
    )

    assert resolution.action == "human_intervention"
