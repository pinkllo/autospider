from __future__ import annotations

import asyncio

from autospider.common.som.mark_id_validator import MarkIdValidator
from autospider.common.types import BoundingBox, ElementMark, SoMSnapshot


def _make_mark(mark_id: int, text: str) -> ElementMark:
    return ElementMark(
        mark_id=mark_id,
        tag="a",
        text=text,
        bbox=BoundingBox(x=0, y=0, width=100, height=20),
        center_normalized=(0.5, 0.5),
    )


def _make_snapshot(*texts: str) -> SoMSnapshot:
    return SoMSnapshot(
        url="https://example.com/list",
        title="test",
        viewport_width=1280,
        viewport_height=720,
        marks=[_make_mark(index, text) for index, text in enumerate(texts, start=1)],
        timestamp=0.0,
    )


def test_validate_mark_id_uses_unique_longest_prefix_as_fallback():
    validator = MarkIdValidator(debug=False)
    snapshot = _make_snapshot(
        "沪昆线金滩等5站站线承导线及相关设备大修等2个项目工程施工总价承包招标（标段一）",
        "广州市黄埔区云埔街火村社区莲潭经济合作社城中村改造项目",
    )

    resolved, results = asyncio.run(
        validator.validate_mark_id_text_map(
            {
                "99": "沪昆线金滩等5站站线承导线及相关设备大修等2个项目工程施工总价承包招标- 沪昆线金滩等5站站线承导线..."
            },
            snapshot,
            page=None,
        )
    )

    assert resolved == [1]
    assert results[0].status == "text_prefix_unique"
    assert results[0].resolved_mark_id == 1


def test_validate_mark_id_keeps_ambiguous_when_longest_prefix_is_tied():
    validator = MarkIdValidator(debug=False)
    snapshot = _make_snapshot(
        "广东省公共资源交易平台工程建设项目公告",
        "广东省公共资源交易平台政府采购公告",
    )

    resolved, results = asyncio.run(
        validator.validate_mark_id_text_map(
            {"99": "广东省公共资源交易平台项目..."},
            snapshot,
            page=None,
        )
    )

    assert resolved == []
    assert results[0].status == "text_prefix_ambiguous"
    assert results[0].candidate_mark_ids == [1, 2]


def test_validate_mark_id_rejects_prefixes_that_are_too_short():
    validator = MarkIdValidator(debug=False)
    snapshot = _make_snapshot(
        "广东省公共资源交易平台工程建设项目公告",
        "广东省人民政府采购网项目公告",
    )

    resolved, results = asyncio.run(
        validator.validate_mark_id_text_map(
            {"99": "广东省"},
            snapshot,
            page=None,
        )
    )

    assert resolved == []
    assert results[0].status == "text_not_found"
    assert results[0].candidate_mark_ids == []
