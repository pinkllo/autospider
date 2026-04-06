from __future__ import annotations

from autospider.crawler.planner.planner_artifacts import PlannerArtifacts
from autospider.domain.planning import PlanJournalEntry, PlanNode, PlanNodeType, SubTask, TaskPlan


def test_build_knowledge_doc_renders_nodes_and_journal():
    artifacts = PlannerArtifacts(
        site_url="https://example.com/root",
        user_request="采集各分类项目名称",
        output_dir="output",
    )
    plan = TaskPlan(
        plan_id="plan_001",
        original_request="采集各分类项目名称",
        site_url="https://example.com/root",
        subtasks=[
            SubTask(
                id="leaf_001",
                name="工程建设",
                list_url="https://example.com/gcjs",
                task_description="采集工程建设列表",
                context={"category_name": "工程建设"},
                plan_node_id="node_002",
            )
        ],
        nodes=[
            PlanNode(
                node_id="node_001",
                parent_node_id=None,
                name="站点首页",
                node_type=PlanNodeType.CATEGORY,
                url="https://example.com/root",
                observations="存在多个分类入口",
                depth=0,
                children_count=1,
            ),
            PlanNode(
                node_id="node_002",
                parent_node_id="node_001",
                name="工程建设",
                node_type=PlanNodeType.LEAF,
                url="https://example.com/gcjs",
                task_description="采集工程建设列表",
                context={"category_name": "工程建设"},
                depth=1,
                subtask_id="leaf_001",
                is_leaf=True,
                executable=True,
            ),
        ],
        journal=[
            PlanJournalEntry(
                entry_id="journal_0001",
                node_id="node_001",
                phase="planning",
                action="expand_category",
                reason="识别出工程建设分类",
                evidence="左侧导航存在工程建设入口",
                metadata={"children_count": "1"},
                created_at="2026-04-05T20:00:00",
            )
        ],
        total_subtasks=1,
    )

    content = artifacts.build_knowledge_doc(plan)

    assert "# 采集计划: example.com" in content
    assert "### 站点首页（1 个子节点）" in content
    assert "#### Journal" in content
    assert "[planning] expand_category: 识别出工程建设分类" in content
    assert "#### 工程建设 ✅" in content
    assert '"category_name": "工程建设"' in content
