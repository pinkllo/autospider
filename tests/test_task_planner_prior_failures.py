"""Phase-1 regression test for TaskPlanner.prior_failures rendering.

We exercise ``_format_prior_failures`` directly to avoid booting a Playwright
browser/LLM — the rendering logic alone determines whether replan evidence
reaches the prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner


def _planner_with_failures(failures: list[dict]) -> TaskPlanner:
    instance = TaskPlanner.__new__(TaskPlanner)
    instance.prior_failures = [dict(item) for item in failures]
    return instance


def test_format_prior_failures_empty_returns_placeholder() -> None:
    planner = _planner_with_failures([])

    assert planner._format_prior_failures() == "（无）"


def test_format_prior_failures_lists_category_and_detail() -> None:
    failures = [
        {
            "category": "rule_stale",
            "detail": "xpath_no_longer_matches",
            "metadata": {"subtask_id": "sub_001", "terminal_reason": "detail_click_failed"},
        },
        {
            "category": "state_mismatch",
            "detail": "dom_changed_between_steps",
            "metadata": {"subtask_id": "sub_002"},
        },
    ]
    planner = _planner_with_failures(failures)

    text = planner._format_prior_failures()

    assert "[rule_stale]" in text
    assert "xpath_no_longer_matches" in text
    assert "subtask=sub_001" in text
    assert "reason=detail_click_failed" in text
    assert "[state_mismatch]" in text
    assert "subtask=sub_002" in text


def test_format_prior_failures_truncates_when_over_limit() -> None:
    failures = [
        {"category": "rule_stale", "detail": f"case_{idx}", "metadata": {}} for idx in range(8)
    ]
    planner = _planner_with_failures(failures)

    text = planner._format_prior_failures(limit=3)

    # 只展示 3 条 bullet + 1 条汇总提示
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    assert len(non_empty_lines) == 4
    assert non_empty_lines[-1].startswith("- ...（共 8 条失败证据")


def test_format_prior_failures_keeps_newest_entries_on_truncation() -> None:
    """当历史超限时，必须保留最近产生的证据，最旧的证据应被剔除。

    这是 replan 链路的核心不变量：长循环下只有最近的失败信号对下一步策略有指导意义。
    """
    failures = [
        {"category": "rule_stale", "detail": f"case_{idx}", "metadata": {}} for idx in range(8)
    ]
    planner = _planner_with_failures(failures)

    text = planner._format_prior_failures(limit=3)

    # 最新的三条：case_5, case_6, case_7 必须出现
    assert "case_5" in text
    assert "case_6" in text
    assert "case_7" in text
    # 最旧的若干条必须被剔除，避免把过期证据当作最新 mode 误导 planner
    for stale_idx in range(5):
        assert f"case_{stale_idx}" not in text, f"stale case_{stale_idx} leaked into prompt"
