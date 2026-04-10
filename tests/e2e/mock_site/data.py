from __future__ import annotations

from dataclasses import dataclass

TOTAL_PAGES = 2
PAGE_SIZE = 4


@dataclass(frozen=True, slots=True)
class MockDetailRecord:
    slug: str
    title: str
    publish_date: str
    budget: str
    attachment_name: str

    def detail_path(self, *, category: str) -> str:
        return f"/details/{category}/{self.slug}"

    def attachment_path(self, *, category: str) -> str:
        return f"/downloads/{category}/{self.slug}.pdf"


ANNOUNCEMENT_RECORDS = (
    MockDetailRecord(
        slug="notice-alpha",
        title="关于自动驾驶示范区道路养护项目的通知公告",
        publish_date="2026-03-01",
        budget="1280000",
        attachment_name="道路养护项目公告.pdf",
    ),
    MockDetailRecord(
        slug="notice-beta",
        title="智慧交通平台升级项目资格预审通知公告",
        publish_date="2026-03-03",
        budget="980000",
        attachment_name="资格预审通知.pdf",
    ),
    MockDetailRecord(
        slug="notice-gamma",
        title="车路协同边缘节点采购项目通知公告",
        publish_date="2026-03-06",
        budget="1560000",
        attachment_name="边缘节点采购公告.pdf",
    ),
    MockDetailRecord(
        slug="notice-delta",
        title="智能网联测试场维保服务项目通知公告",
        publish_date="2026-03-09",
        budget="870000",
        attachment_name="测试场维保服务公告.pdf",
    ),
    MockDetailRecord(
        slug="notice-epsilon",
        title="智能公交数据接入服务项目通知公告",
        publish_date="2026-03-12",
        budget="640000",
        attachment_name="数据接入服务公告.pdf",
    ),
    MockDetailRecord(
        slug="notice-zeta",
        title="北斗定位模块采购项目通知公告",
        publish_date="2026-03-15",
        budget="450000",
        attachment_name="北斗定位模块采购公告.pdf",
    ),
    MockDetailRecord(
        slug="notice-eta",
        title="园区充电设施运维服务项目通知公告",
        publish_date="2026-03-18",
        budget="720000",
        attachment_name="充电设施运维公告.pdf",
    ),
)

ANNOUNCEMENT_PAGE_SLUGS = (
    ("notice-alpha", "notice-beta", "notice-gamma", "notice-delta"),
    ("notice-delta", "notice-epsilon", "notice-zeta", "notice-eta"),
)

DEAL_RECORDS = (
    MockDetailRecord(
        slug="deal-alpha",
        title="自动驾驶安全巡检设备采购成交结果",
        publish_date="2026-03-02",
        budget="510000",
        attachment_name="安全巡检设备成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-beta",
        title="测试道路高精地图更新服务成交结果",
        publish_date="2026-03-05",
        budget="860000",
        attachment_name="高精地图更新成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-gamma",
        title="智慧路口摄像头改造项目成交结果",
        publish_date="2026-03-07",
        budget="1320000",
        attachment_name="摄像头改造成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-delta",
        title="车端终端批量标定服务成交结果",
        publish_date="2026-03-10",
        budget="390000",
        attachment_name="终端标定服务成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-epsilon",
        title="车路协同算法测评服务成交结果",
        publish_date="2026-03-13",
        budget="770000",
        attachment_name="算法测评服务成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-zeta",
        title="多源传感器时间同步改造项目成交结果",
        publish_date="2026-03-16",
        budget="680000",
        attachment_name="时间同步改造成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-eta",
        title="测试牌照管理系统优化项目成交结果",
        publish_date="2026-03-19",
        budget="540000",
        attachment_name="牌照管理系统优化成交结果.pdf",
    ),
    MockDetailRecord(
        slug="deal-theta",
        title="无人接驳站点监控升级项目成交结果",
        publish_date="2026-03-21",
        budget="920000",
        attachment_name="站点监控升级成交结果.pdf",
    ),
)

DEAL_PAGE_SLUGS = (
    ("deal-alpha", "deal-beta", "deal-gamma", "deal-delta"),
    ("deal-epsilon", "deal-zeta", "deal-eta", "deal-theta"),
)

ANNOUNCEMENT_BY_SLUG = {record.slug: record for record in ANNOUNCEMENT_RECORDS}
DEAL_BY_SLUG = {record.slug: record for record in DEAL_RECORDS}


def get_announcement_page(page: int) -> tuple[MockDetailRecord, ...]:
    return _get_page_records(
        page=page,
        slugs_by_page=ANNOUNCEMENT_PAGE_SLUGS,
        records_by_slug=ANNOUNCEMENT_BY_SLUG,
    )


def get_deal_page(page: int) -> tuple[MockDetailRecord, ...]:
    return _get_page_records(
        page=page,
        slugs_by_page=DEAL_PAGE_SLUGS,
        records_by_slug=DEAL_BY_SLUG,
    )


def get_record(*, category: str, slug: str) -> MockDetailRecord | None:
    if category == "announcement":
        return ANNOUNCEMENT_BY_SLUG.get(slug)
    if category == "deal":
        return DEAL_BY_SLUG.get(slug)
    return None


def _get_page_records(
    *,
    page: int,
    slugs_by_page: tuple[tuple[str, ...], ...],
    records_by_slug: dict[str, MockDetailRecord],
) -> tuple[MockDetailRecord, ...]:
    index = max(1, min(page, len(slugs_by_page))) - 1
    return tuple(records_by_slug[slug] for slug in slugs_by_page[index])
