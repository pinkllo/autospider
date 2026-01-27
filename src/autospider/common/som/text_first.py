from __future__ import annotations

"""
文本优先的 mark_id 解析/消歧工具

修改原因：
- 项目内多个模块都会让视觉 LLM 返回 mark_id（有时还会返回该元素文本）。
- 视觉模型最常见的错误是：文本选对了，但 mark_id 读错；或同一文本在页面多处出现导致歧义。
- 为提升鲁棒性，全项目统一使用“文本优先、歧义重选、未命中报错”的策略。
"""

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import config
from ..protocol import parse_json_dict_from_llm, protocol_to_legacy_selected_mark
from common.utils.prompt_template import render_template
from ..utils.paths import get_prompt_path
from .mark_id_validator import MarkIdValidator
from .api import capture_screenshot_with_custom_marks

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI
    from playwright.async_api import Page
    from ..types import ElementMark, SoMSnapshot


PROMPT_TEMPLATE_PATH = get_prompt_path("disambiguate_by_text.yaml")


async def resolve_mark_ids_from_map(
    *,
    page: "Page",
    llm: "ChatOpenAI",
    snapshot: "SoMSnapshot",
    mark_id_text_map: dict[str, str],
    max_retries: int | None = None,
) -> list[int]:
    """解析 LLM 返回的 mark_id_text_map（文本优先）

    Returns:
        去重后的最终 mark_id 列表
    """
    validator = MarkIdValidator()
    resolved_mark_ids, results = await validator.validate_mark_id_text_map(
        mark_id_text_map, snapshot, page=page
    )

    final_ids = list(resolved_mark_ids)

    retries = max(
        1,
        int(
            max_retries if max_retries is not None else config.url_collector.max_validation_retries
        ),
    )
    allow_partial = len(mark_id_text_map) > 1  # 修改原因：批量选择时，允许少量未命中不阻断全局流程

    for r in results:
        if r.is_valid:
            continue

        if r.status == "text_ambiguous" and r.candidate_mark_ids:
            candidates = [m for m in snapshot.marks if m.mark_id in set(r.candidate_mark_ids)]
            selected = await disambiguate_mark_id_by_text(
                page=page,
                llm=llm,
                candidates=candidates,
                target_text=r.llm_text,
                max_retries=retries,
            )
            if selected is None:
                if allow_partial:
                    print(f"[TextFirst] ⚠ 歧义重选失败，已跳过该条: text='{r.llm_text[:60]}'")
                    continue
                raise ValueError(
                    f"歧义重选失败: text='{r.llm_text}' candidates={r.candidate_mark_ids}"
                )
            final_ids.append(selected)
            continue

        if r.status == "text_not_found":
            if allow_partial:
                print(f"[TextFirst] ⚠ 未命中文本，已跳过该条: '{r.llm_text[:60]}'")
                continue
            raise ValueError(f"未在当前候选框中找到目标文本: '{r.llm_text}'")

    # 去重保持顺序
    seen = set()
    deduped: list[int] = []
    for mid in final_ids:
        if mid not in seen:
            deduped.append(mid)
            seen.add(mid)

    if not deduped:
        # 修改原因：即使允许 partial，也不能返回空集合，否则下游无可执行目标
        raise ValueError("未能从当前候选框中解析出任何可用的 mark_id（文本匹配全部失败）")

    return deduped


async def resolve_single_mark_id(
    *,
    page: "Page",
    llm: "ChatOpenAI",
    snapshot: "SoMSnapshot",
    mark_id: int | None,
    target_text: str,
    max_retries: int | None = None,
) -> int:
    """解析单个 mark_id（文本优先）

    修改原因：Agent 的 click/type/extract 等动作通常是 (mark_id + target_text) 形式，
    需要在执行前纠正 mark_id（或在歧义时重选），避免误点误输。
    """
    key = str(mark_id) if mark_id is not None else "-1"
    resolved = await resolve_mark_ids_from_map(
        page=page,
        llm=llm,
        snapshot=snapshot,
        mark_id_text_map={key: target_text},
        max_retries=max_retries,
    )
    if not resolved:
        raise ValueError(f"无法解析目标文本对应的元素: '{target_text}'")
    return resolved[0]


async def disambiguate_mark_id_by_text(
    *,
    page: "Page",
    llm: "ChatOpenAI",
    candidates: list["ElementMark"],
    target_text: str,
    max_retries: int = 1,
) -> int | None:
    """当同一文本命中多个候选元素时，截图让 LLM 重选（只给候选截图+新 mark）"""
    if not candidates:
        return None

    overlay_marks = [
        {"mark_id": str(i + 1), "bbox": c.bbox.model_dump()}
        for i, c in enumerate(candidates[:20])  # 防止候选过多影响可读性
    ]

    system_prompt = render_template(PROMPT_TEMPLATE_PATH, section="system_prompt")
    user_message = render_template(
        PROMPT_TEMPLATE_PATH,
        section="user_message",
        variables={
            "target_text": target_text,
            "candidate_count": str(len(overlay_marks)),
        },
    )

    attempts = max(1, int(max_retries or 1))
    for _ in range(attempts):
        _, screenshot_base64 = await capture_screenshot_with_custom_marks(
            page, overlay_marks, hide_original_som=True
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
                    },
                ]
            ),
        ]

        response = await llm.ainvoke(messages)
        response_text = getattr(response, "content", "") or ""

        data = parse_json_dict_from_llm(response_text)
        if not data:
            continue

        data = protocol_to_legacy_selected_mark(data)

        selected = data.get("selected_mark_id") or data.get("mark_id")
        try:
            selected_index = int(selected)
        except (TypeError, ValueError):
            continue

        if 1 <= selected_index <= len(overlay_marks):
            return candidates[selected_index - 1].mark_id

    return None
