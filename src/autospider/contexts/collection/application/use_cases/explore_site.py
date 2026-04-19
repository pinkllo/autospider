from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autospider.common.config import config
from autospider.common.logger import get_logger
from autospider.common.som import capture_screenshot_with_marks, clear_overlay, inject_and_scan
from autospider.common.som.text_first import (
    resolve_mark_ids_from_map,
    resolve_single_mark_id,
)
from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
from autospider.crawler.collector import DetailPageVisit, smart_scroll

if TYPE_CHECKING:
    from autospider.common.types import SoMSnapshot

logger = get_logger(__name__)

CurrentDetailHandler = Callable[[int], Awaitable[bool]]
SelectDetailHandler = Callable[[dict[str, Any], "SoMSnapshot", str, int], Awaitable[int]]
ClickDetailHandler = Callable[[dict[str, Any], "SoMSnapshot"], Awaitable[bool]]


def _serialize_selected_skills(selected: Sequence[Any]) -> list[dict[str, str]]:
    return [
        {
            "name": str(skill.name),
            "description": str(skill.description),
            "path": str(skill.path),
            "domain": str(skill.domain),
        }
        for skill in selected
    ]


async def prepare_explore_skill_context(
    *,
    skill_runtime: SkillRuntime,
    phase: str,
    url: str,
    task_context: dict[str, Any],
    llm: Any,
    preselected_skills: list[dict] | None,
) -> tuple[list[dict[str, str]], str]:
    selected = await skill_runtime.get_or_select(
        phase=phase,
        url=url,
        task_context=task_context,
        llm=llm,
        preselected_skills=preselected_skills,
    )
    return (
        _serialize_selected_skills(selected),
        skill_runtime.format_selected_skills_context(skill_runtime.load_selected_bodies(selected)),
    )


async def run_detail_explore_loop(
    *,
    page: Any,
    screenshots_dir: Path,
    llm_decision_maker: Any,
    explore_count: int,
    on_current_detail: CurrentDetailHandler,
    on_select_detail_links: SelectDetailHandler,
    on_click_to_enter: ClickDetailHandler,
) -> None:
    explored = 0
    max_attempts = explore_count * 5
    attempts = 0
    consecutive_bottom_hits = 0
    max_bottom_hits = 3

    while explored < explore_count and attempts < max_attempts:
        attempts += 1
        logger.info(
            "\n[Explore] ===== 尝试 %d/%d，已探索 %d/%d =====",
            attempts,
            max_attempts,
            explored,
            explore_count,
        )

        logger.info("[Explore] 扫描页面...")
        await clear_overlay(page)
        snapshot = await inject_and_scan(page)
        screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(page)

        screenshot_path = screenshots_dir / f"explore_{attempts:03d}.png"
        screenshot_path.write_bytes(screenshot_bytes)
        logger.info("[Explore] 截图已保存: %s", screenshot_path.name)

        logger.info("[Explore] 调用 LLM 决策...")
        llm_decision = await llm_decision_maker.ask_for_decision(snapshot, screenshot_base64)

        if llm_decision is None:
            logger.info("[Explore] LLM 决策失败，尝试滚动...")
            if await smart_scroll(page):
                consecutive_bottom_hits = 0
            else:
                consecutive_bottom_hits += 1
                logger.info("[Explore] 已到达页面底部 (%d/%d)", consecutive_bottom_hits, max_bottom_hits)
                if consecutive_bottom_hits >= max_bottom_hits:
                    logger.info("[Explore] ⚠ 连续到达页面底部，停止探索")
                    break
            continue

        decision_type = llm_decision.get("action")
        decision_args = llm_decision.get("args") if isinstance(llm_decision.get("args"), dict) else {}

        if (
            decision_type == "report"
            and (decision_args.get("kind") or "").lower() == "page_kind"
            and (decision_args.get("page_kind") or "").lower() == "detail"
        ):
            if await on_current_detail(explored):
                explored += 1
                consecutive_bottom_hits = 0
            else:
                if not await smart_scroll(page):
                    consecutive_bottom_hits += 1
                    if consecutive_bottom_hits >= max_bottom_hits:
                        break
                else:
                    consecutive_bottom_hits = 0
            continue

        if decision_type == "select" and (decision_args.get("purpose") or "").lower() in {"detail_links", "detail_link", "detail"}:
            new_explored = await on_select_detail_links(llm_decision, snapshot, screenshot_base64, explored)
            if new_explored > explored:
                explored = new_explored
                consecutive_bottom_hits = 0
            else:
                if not await smart_scroll(page):
                    consecutive_bottom_hits += 1
                    if consecutive_bottom_hits >= max_bottom_hits:
                        break
                else:
                    consecutive_bottom_hits = 0
            continue

        if decision_type == "click":
            if await on_click_to_enter(llm_decision, snapshot):
                explored += 1
                consecutive_bottom_hits = 0
            continue

        if decision_type == "scroll":
            if await smart_scroll(page):
                consecutive_bottom_hits = 0
            else:
                consecutive_bottom_hits += 1
                if consecutive_bottom_hits >= max_bottom_hits:
                    break


def build_detail_visit(
    *,
    list_url: str,
    detail_url: str,
    step_index: int,
    element: Any | None = None,
    clicked_element_mark_id: int = 0,
    clicked_element_tag: str = "page",
    clicked_element_text: str = "当前页面",
    clicked_element_href: str = "",
    clicked_element_role: str = "page",
) -> DetailPageVisit:
    if element is not None:
        clicked_element_mark_id = int(getattr(element, "mark_id", clicked_element_mark_id) or 0)
        clicked_element_tag = str(getattr(element, "tag", clicked_element_tag) or "")
        clicked_element_text = str(getattr(element, "text", clicked_element_text) or "")
        clicked_element_href = str(getattr(element, "href", clicked_element_href) or "")
        clicked_element_role = str(getattr(element, "role", clicked_element_role) or "")
        xpath_candidates = [
            {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
            for c in (getattr(element, "xpath_candidates", None) or [])
        ]
    else:
        xpath_candidates = []

    return DetailPageVisit(
        list_page_url=list_url,
        detail_page_url=detail_url,
        clicked_element_mark_id=clicked_element_mark_id,
        clicked_element_tag=clicked_element_tag,
        clicked_element_text=clicked_element_text,
        clicked_element_href=clicked_element_href or detail_url,
        clicked_element_role=clicked_element_role,
        clicked_element_xpath_candidates=xpath_candidates,
        step_index=step_index,
        timestamp=datetime.now().isoformat(),
    )


def extract_mark_id_text_map(items: Sequence[Any]) -> dict[str, str]:
    mark_id_text_map: dict[str, str] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or item.get("target_text") or "").strip()
        if not text_value:
            continue
        raw_mark_id = item.get("mark_id")
        key = str(raw_mark_id) if raw_mark_id is not None else f"text_only_{idx}"
        mark_id_text_map[key] = text_value
    return mark_id_text_map


async def resolve_selected_mark_ids(
    *,
    page: Any,
    llm: Any,
    snapshot: "SoMSnapshot",
    mark_id_text_map: dict[str, str],
    fallback_mark_ids: Sequence[Any] | None = None,
) -> list[int]:
    if mark_id_text_map:
        logger.info("[Explore] LLM 返回了 %d 个 mark_id-文本映射", len(mark_id_text_map))
        should_resolve_by_text = config.url_collector.validate_mark_id or any(
            not str(key).isdigit() for key in mark_id_text_map.keys()
        )
        if should_resolve_by_text:
            try:
                return await resolve_mark_ids_from_map(
                    page=page,
                    llm=llm,
                    snapshot=snapshot,
                    mark_id_text_map=mark_id_text_map,
                    max_retries=config.url_collector.max_validation_retries,
                )
            except Exception as exc:
                logger.warning("[Explore] 文本解析 mark_id 失败，回退数字 id: %s", exc)
        return [int(key) for key in mark_id_text_map.keys() if str(key).isdigit()]

    if fallback_mark_ids:
        logger.info("[Explore] LLM 返回了 %d 个 mark_ids", len(fallback_mark_ids))
        return [int(mark_id) for mark_id in fallback_mark_ids if str(mark_id).isdigit()]
    return []


async def resolve_click_mark_id(
    *,
    page: Any,
    llm: Any,
    snapshot: "SoMSnapshot",
    raw_mark_id: Any,
    target_text: str,
) -> int | None:
    try:
        mark_id = int(raw_mark_id) if raw_mark_id is not None else None
    except (TypeError, ValueError):
        mark_id = None

    if target_text and (config.url_collector.validate_mark_id or mark_id is None):
        try:
            return await resolve_single_mark_id(
                page=page,
                llm=llm,
                snapshot=snapshot,
                mark_id=mark_id,
                target_text=target_text,
                max_retries=config.url_collector.max_validation_retries,
            )
        except Exception as exc:
            raise ValueError(f"点击进入详情页：无法根据文本纠正 mark_id: {exc}") from exc

    return mark_id
