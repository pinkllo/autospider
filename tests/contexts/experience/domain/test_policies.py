from __future__ import annotations

import pytest

from autospider.contexts.experience.domain.policies import normalize_skill_status


def test_normalize_skill_status_accepts_allowed_status() -> None:
    assert normalize_skill_status("VALIDATED") == "validated"


def test_normalize_skill_status_rejects_empty_status() -> None:
    with pytest.raises(ValueError, match="status cannot be empty"):
        normalize_skill_status("")


def test_normalize_skill_status_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="invalid status"):
        normalize_skill_status("unknown")
