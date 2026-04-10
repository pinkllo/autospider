from __future__ import annotations

from tests.e2e.contracts import BASE_URL_PLACEHOLDER, GraphE2ECase

BASE_URL = BASE_URL_PLACEHOLDER


def _build_fields() -> list[dict[str, object]]:
    return [
        {"name": "title", "description": "公告标题", "required": True, "data_type": "text"},
        {
            "name": "publish_date",
            "description": "发布日期，格式为 YYYY-MM-DD",
            "required": True,
            "data_type": "date",
        },
        {
            "name": "budget",
            "description": "预算金额，保留币种与单位",
            "required": True,
            "data_type": "text",
        },
        {
            "name": "attachment_url",
            "description": "附件下载链接，返回完整 URL",
            "required": True,
            "data_type": "url",
        },
    ]


def _build_override_task(*, list_url: str, task_description: str, target_url_count: int) -> dict[str, object]:
    return {
        "intent": "crawl",
        "list_url": list_url,
        "task_description": task_description,
        "fields": _build_fields(),
        "max_pages": 2,
        "target_url_count": target_url_count,
        "consumer_concurrency": 1,
        "field_explore_count": 3,
        "field_validate_count": 4,
    }


ALL_CASES: tuple[GraphE2ECase, ...] = (
    GraphE2ECase(
        case_id="graph_all_categories",
        request_text="请采集测试门户里所有分类的公告，并返回标准字段。",
        clarification_answers=(
            f"从 {BASE_URL}/ 开始，覆盖通知公告和成交结果两个栏目，只提取 title、publish_date、budget、attachment_url。",
        ),
        override_task=_build_override_task(
            list_url=f"{BASE_URL}/",
            task_description="从门户首页进入通知公告与成交结果两个栏目，采集全部详情页，并提取标题、发布日期、预算金额和附件链接。",
            target_url_count=15,
        ),
        expected_records_file="graph_direct_list_pagination_dedupe.records.json",
        expected_summary={"merged_items": 15, "unique_urls": 15},
    ),
    GraphE2ECase(
        case_id="graph_same_page_variant",
        request_text="请只采集测试门户中成交结果栏目里的公告。",
        clarification_answers=(
            f"从 {BASE_URL}/ 开始，只切换到成交结果 tab，提取 title、publish_date、budget、attachment_url。",
        ),
        override_task=_build_override_task(
            list_url=f"{BASE_URL}/",
            task_description="从门户首页切换到成交结果 tab，只采集成交结果栏目详情页，并提取标题、发布日期、预算金额和附件链接。",
            target_url_count=8,
        ),
        expected_records_file="graph_same_page_variant.records.json",
        expected_summary={"merged_items": 8, "unique_urls": 8},
    ),
    GraphE2ECase(
        case_id="graph_direct_list_pagination_dedupe",
        request_text="请从通知公告列表页开始采集，并对跨页重复链接去重。",
        clarification_answers=(
            f"列表页是 {BASE_URL}/announcements，只采集通知公告栏目，提取 title、publish_date、budget、attachment_url。",
        ),
        override_task=_build_override_task(
            list_url=f"{BASE_URL}/announcements",
            task_description="从通知公告列表页直接开始，遍历分页并对跨页重复详情链接去重，提取标题、发布日期、预算金额和附件链接。",
            target_url_count=7,
        ),
        expected_records_file="graph_all_categories.records.json",
        expected_summary={"merged_items": 7, "unique_urls": 7},
    ),
)

CASE_BY_ID = {case.case_id: case for case in ALL_CASES}

__all__ = ["ALL_CASES", "CASE_BY_ID"]
