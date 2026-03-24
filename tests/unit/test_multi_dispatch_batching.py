from __future__ import annotations

from autospider.graph.subgraphs.multi_dispatch import prepare_dispatch_batch


def test_prepare_dispatch_batch_respects_max_concurrent():
    result = prepare_dispatch_batch(
        {
            "normalized_params": {"max_concurrent": 2},
            "dispatch_queue": [
                {"id": "sub_01"},
                {"id": "sub_02"},
                {"id": "sub_03"},
            ],
            "spawned_subtasks": [{"id": "old_spawn"}],
        }
    )

    assert result["current_batch"] == [{"id": "sub_01"}, {"id": "sub_02"}]
    assert result["dispatch_queue"] == [{"id": "sub_03"}]
    assert result["spawned_subtasks"] == []
