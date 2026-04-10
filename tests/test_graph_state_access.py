from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.state_access import dispatch_summary, select_summary


def test_dispatch_summary_reads_root_dispatch_result() -> None:
    state = {
        "dispatch": {"summary": {}},
        "dispatch_result": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36},
        "summary": {"merged_items": 31},
    }

    assert dispatch_summary(state) == {
        "total": 4,
        "completed": 4,
        "failed": 0,
        "total_collected": 36,
    }


def test_select_summary_merges_dispatch_and_result_metrics() -> None:
    state = {
        "dispatch": {"summary": {}},
        "dispatch_result": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36},
        "result": {"summary": {"merged_items": 31, "unique_urls": 31}},
        "summary": {"thread_id": "thread-1", "entry_mode": "chat_pipeline"},
    }

    assert select_summary(state) == {
        "total": 4,
        "completed": 4,
        "failed": 0,
        "total_collected": 36,
        "merged_items": 31,
        "unique_urls": 31,
        "thread_id": "thread-1",
        "entry_mode": "chat_pipeline",
    }
