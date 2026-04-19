from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.crawler.planner.planner_analysis_postprocess import (
    PlannerAnalysisPostProcessMixin,
)
from autospider.contexts.planning.domain.services import (
    PlannerCategorySemanticsMixin,
    PlannerSubtaskBuilderMixin,
)
from autospider.contexts.planning.domain import SubTaskMode


class _PlannerHarness(
    PlannerCategorySemanticsMixin,
    PlannerSubtaskBuilderMixin,
    PlannerAnalysisPostProcessMixin,
):
    def __init__(
        self,
        *,
        user_request: str = "请按学科分类采集专业目录，每类前10条，样例方向是交通运输工程。",
        grouping_semantics: dict | None = None,
    ) -> None:
        self.user_request = user_request
        self.grouping_semantics = {
            "group_by": "category",
            "per_group_target_count": 10,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": ["交通运输工程"],
        }
        if grouping_semantics:
            self.grouping_semantics.update(grouping_semantics)
        self._sibling_category_registry: dict[str, set[str]] = {}

    def _append_observation_note(self, result: dict, note: str) -> dict:
        observations = str(result.get("observations") or "").strip()
        result["observations"] = f"{observations}\n{note}".strip() if observations else note
        return result

    def _get_grouping_semantics(self) -> dict:
        return dict(self.grouping_semantics)


def test_postprocess_builds_category_subtasks_from_page_facts_in_auto_mode() -> None:
    planner = _PlannerHarness()
    snapshot = SimpleNamespace(marks=[])
    analysis = {
        "page_type": "category",
        "name": "本科专业分类导航",
        "observations": "主体=分类导航; 支持同页切换",
        "category_controls_present": True,
        "supports_same_page_variant_switch": True,
        "current_selected_category": "",
        "category_candidates": [
            {"name": "工学-土木工程", "mark_id": 1, "link_text": "工学-土木工程"},
            {"name": "工学-交通运输工程", "mark_id": 2, "link_text": "工学-交通运输工程"},
            {"name": "工学-水利工程", "mark_id": 3, "link_text": "工学-水利工程"},
            {"name": "工学-测绘工程", "mark_id": 4, "link_text": "工学-测绘工程"},
        ],
        "subtasks": [],
    }

    normalized = planner._post_process_analysis(analysis, snapshot, node_context={})

    names = [item["name"] for item in normalized["subtasks"]]
    assert names == [
        "工学-土木工程",
        "工学-交通运输工程",
        "工学-水利工程",
        "工学-测绘工程",
    ]


def test_postprocess_prefers_category_candidates_over_llm_subtasks() -> None:
    planner = _PlannerHarness()
    snapshot = SimpleNamespace(marks=[])
    analysis = {
        "page_type": "category",
        "name": "本科专业分类导航",
        "observations": "主体=分类导航; 支持同页切换",
        "category_controls_present": True,
        "supports_same_page_variant_switch": True,
        "current_selected_category": "",
        "category_candidates": [
            {"name": "工学-土木工程", "mark_id": 1, "link_text": "工学-土木工程"},
            {"name": "工学-交通运输工程", "mark_id": 2, "link_text": "工学-交通运输工程"},
            {"name": "工学-水利工程", "mark_id": 3, "link_text": "工学-水利工程"},
            {"name": "工学-测绘工程", "mark_id": 4, "link_text": "工学-测绘工程"},
        ],
        "subtasks": [
            {
                "name": "交通运输工程",
                "mark_id": 99,
                "link_text": "交通运输工程",
                "task_description": "根据用户措辞推测出的单个分类",
            }
        ],
    }

    normalized = planner._post_process_analysis(analysis, snapshot, node_context={})

    names = [item["name"] for item in normalized["subtasks"]]
    assert names == [
        "工学-土木工程",
        "工学-交通运输工程",
        "工学-水利工程",
        "工学-测绘工程",
    ]


def test_grouped_path_without_category_candidates_does_not_trust_llm_subtasks() -> None:
    planner = _PlannerHarness()
    snapshot = SimpleNamespace(marks=[])
    analysis = {
        "page_type": "category",
        "name": "本科专业分类导航",
        "observations": "主体=分类导航",
        "category_controls_present": True,
        "supports_same_page_variant_switch": True,
        "current_selected_category": "",
        "category_candidates": [],
        "subtasks": [
            {
                "name": "交通运输工程",
                "mark_id": 99,
                "link_text": "交通运输工程",
                "task_description": "根据话术补出来的分类",
            }
        ],
    }

    normalized = planner._post_process_analysis(analysis, snapshot, node_context={})

    assert normalized["subtasks"] == []
    assert normalized["category_candidates"] == []
    assert "按页面事实中的分类候选生成子任务" not in str(normalized.get("observations") or "")
    assert "未采用 subtasks 作为兜底来源" in str(normalized.get("observations") or "")


def test_manual_mode_keeps_only_matching_page_fact_candidates() -> None:
    planner = _PlannerHarness(
        grouping_semantics={
            "category_discovery_mode": "manual",
            "requested_categories": ["交通运输工程", "水利工程"],
        }
    )
    snapshot = SimpleNamespace(marks=[])
    analysis = {
        "page_type": "category",
        "name": "本科专业分类导航",
        "observations": "主体=分类导航; 支持同页切换",
        "category_controls_present": True,
        "supports_same_page_variant_switch": True,
        "current_selected_category": "",
        "category_candidates": [
            {"name": "工学-土木工程", "mark_id": 1, "link_text": "工学-土木工程"},
            {"name": "工学-交通运输工程", "mark_id": 2, "link_text": "工学-交通运输工程"},
            {"name": "工学-水利工程", "mark_id": 3, "link_text": "工学-水利工程"},
            {"name": "工学-测绘工程", "mark_id": 4, "link_text": "工学-测绘工程"},
        ],
        "subtasks": [],
    }

    normalized = planner._post_process_analysis(analysis, snapshot, node_context={})

    names = [item["name"] for item in normalized["subtasks"]]
    assert names == [
        "工学-交通运输工程",
        "工学-水利工程",
    ]


def test_per_group_target_count_drives_grouped_category_task_description() -> None:
    planner = _PlannerHarness(
        user_request="请按学科分类采集专业目录，每类前10条，样例方向是交通运输工程。",
        grouping_semantics={"per_group_target_count": 3},
    )
    snapshot = SimpleNamespace(marks=[])
    analysis = {
        "page_type": "category",
        "name": "本科专业分类导航",
        "observations": "主体=分类导航; 支持同页切换",
        "category_controls_present": True,
        "supports_same_page_variant_switch": True,
        "current_selected_category": "",
        "category_candidates": [
            {"name": "工学-交通运输工程", "mark_id": 2, "link_text": "工学-交通运输工程"},
        ],
        "subtasks": [],
    }

    normalized = planner._post_process_analysis(analysis, snapshot, node_context={})

    task_description = normalized["subtasks"][0]["task_description"]
    assert "各3条" in task_description
    assert "各10条" not in task_description


def test_grouped_category_subtask_records_scope_fixed_fields_and_target_count() -> None:
    planner = _PlannerHarness(grouping_semantics={"per_group_target_count": 3})
    context = planner._build_subtask_context("工学-交通运输工程")
    variants = [
        SimpleNamespace(
            resolved_url="https://example.com/majors?category=traffic",
            anchor_url="https://example.com/majors",
            page_state_signature="sig-traffic",
            variant_label="工学 > 交通运输工程",
            nav_steps=[{"action": "click", "target_text": "工学-交通运输工程"}],
            context=context,
        )
    ]
    analysis = {
        "subtasks": [
            {
                "name": "工学-交通运输工程",
                "scope_key": "category:工学 > 交通运输工程",
                "scope_label": "工学 > 交通运输工程",
            }
        ]
    }

    subtasks = planner._build_subtasks_from_variants(
        variants,
        analysis=analysis,
        depth=0,
        mode=SubTaskMode.COLLECT,
    )

    assert len(subtasks) == 1
    subtask = subtasks[0]
    assert subtask.scope == {
        "key": "category:工学 > 交通运输工程",
        "label": "工学 > 交通运输工程",
        "path": ["工学", "交通运输工程"],
    }
    assert subtask.fixed_fields == {
        "category": "工学 > 交通运输工程",
        "category_name": "工学 > 交通运输工程",
        "分类": "工学 > 交通运输工程",
        "所属分类": "工学 > 交通运输工程",
    }
    assert subtask.fixed_fields["所属分类"] == subtask.scope["label"]
    assert subtask.per_subtask_target_count == 3


def test_planner_prompt_uses_grouping_semantics_instead_of_raw_user_wording() -> None:
    prompt_path = SRC_ROOT / "autospider" / "prompts" / "planner.yaml"
    prompt_text = prompt_path.read_text(encoding="utf-8")

    assert "## 结构化分组语义" in prompt_text
    assert "再判断用户是否要求“按分类分别采集”" not in prompt_text
    assert "只有当用户明确要求“按分类分别采集 / 每类采集 / 各分类采集”" not in prompt_text
    assert "当用户明确点名多个分类" not in prompt_text


def test_looks_like_current_category_requires_explicit_current_selected_category() -> None:
    planner = _PlannerHarness()
    analysis = {
        "observations": "当前选中分类为房屋建筑和市政基础设施工程，同时页面包含交通运输工程、水利工程、其他工程等兄弟分类切换入口。",
        "current_selected_category": "",
    }

    assert planner._looks_like_current_category("交通运输工程", analysis) is False


def test_looks_like_current_category_accepts_explicit_current_selected_category_match() -> None:
    planner = _PlannerHarness()
    analysis = {
        "observations": "当前选中分类为房屋建筑和市政基础设施工程，同时页面包含交通运输工程、水利工程、其他工程等兄弟分类切换入口。",
        "current_selected_category": "房屋建筑和市政基础设施工程",
    }

    assert planner._looks_like_current_category("房屋建筑和市政基础设施工程", analysis) is True
    assert planner._looks_like_current_category("交通运输工程", analysis) is False
