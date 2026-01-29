"""字段提取 LLM 决策器

负责调用 LLM 进行字段提取相关的决策：
- 导航决策：判断目标字段是否可见
- 字段文本提取：识别并提取字段值
- 多候选消歧：从多个匹配中选择正确的
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from common.utils.prompt_template import render_template
from ..common.logger import get_logger
from ..common.utils.paths import get_prompt_path
from ..common.protocol import parse_protocol_message, coerce_bool
from .models import FieldDefinition

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..common.llm import LLMDecider
    from ..common.types import ElementMark, SoMSnapshot, ScrollInfo


# Prompt 模板文件路径
PROMPT_TEMPLATE_PATH = get_prompt_path("field_extractor.yaml")
logger = get_logger(__name__)


class FieldDecider:
    """字段提取 LLM 决策器

    封装所有字段提取相关的 LLM 调用。
    """

    def __init__(
        self,
        page: "Page",
        decider: "LLMDecider",
    ):
        """
        初始化字段决策器

        Args:
            page: Playwright 页面对象
            decider: 多模态 LLM 决策器（已配置好的）
        """
        self.page = page
        self.decider = decider

    def _parse_response_json(self, response_text: str) -> dict | None:
        # 修改原因：解析逻辑统一收口到 common.protocol，避免各处重复补丁。
        return parse_protocol_message(response_text)

    def _compact_text(self, text: str, max_len: int = 60) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) > max_len:
            return cleaned[: max_len - 3] + "..."
        return cleaned

    def _normalize_field_name(self, value: str | None) -> str:
        if not value:
            return ""
        cleaned = re.sub(r"\s+", "", str(value)).strip().lower()
        return cleaned

    def _field_names_match(self, reported: str | None, expected: str) -> bool:
        r = self._normalize_field_name(reported)
        e = self._normalize_field_name(expected)
        return not r or not e or r == e or r in e or e in r

    def _get_candidate_label(self, mark: "ElementMark") -> str:
        if mark.text:
            return mark.text
        if mark.aria_label:
            return f"[aria] {mark.aria_label}"
        if mark.placeholder:
            return f"[placeholder] {mark.placeholder}"
        if mark.href:
            return f"[href] {mark.href}"
        return ""

    def _collect_clickable_candidates(
        self,
        snapshot: "SoMSnapshot",
    ) -> list[tuple[float, "ElementMark", str]]:
        if not snapshot or not snapshot.marks:
            return []

        candidates: list[tuple[float, "ElementMark", str]] = []
        seen_labels: set[str] = set()
        role_bonus = {"tab", "button", "link", "menuitem"}
        tag_bonus = {"button", "a"}

        for mark in snapshot.marks:
            label = self._get_candidate_label(mark)
            if not label:
                continue
            label = self._compact_text(label)
            if not label:
                continue
            label_key = label.lower()
            if label_key in seen_labels:
                continue
            seen_labels.add(label_key)

            confidence = mark.clickability_confidence or 0.5
            score = confidence
            if mark.role in role_bonus:
                score += 0.3
            if mark.tag in tag_bonus:
                score += 0.2
            if mark.text:
                score += 0.1

            candidates.append((score, mark, label))

        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1].center_normalized[1],
                item[1].center_normalized[0],
            )
        )
        return candidates

    def _build_clickable_candidates_text(
        self,
        snapshot: "SoMSnapshot",
        max_candidates: int = 20,
    ) -> tuple[str, int]:
        candidates = self._collect_clickable_candidates(snapshot)
        if not candidates:
            return "无", 0

        lines = []
        for _, mark, label in candidates[:max_candidates]:
            cx, cy = mark.center_normalized
            role_text = mark.role or "none"
            reason = mark.clickability_reason or "unknown"
            conf = mark.clickability_confidence
            conf_text = f"{conf:.2f}" if conf is not None else "n/a"
            lines.append(
                f"- [{mark.mark_id}] {label} "
                f"(tag={mark.tag} role={role_text} click={reason}/{conf_text} "
                f"@{cx:.2f},{cy:.2f})"
            )

        return "\n".join(lines), len(lines)

    def _collect_input_candidates(
        self,
        snapshot: "SoMSnapshot",
    ) -> list[tuple[float, "ElementMark", str]]:
        if not snapshot or not snapshot.marks:
            return []

        candidates: list[tuple[float, "ElementMark", str]] = []
        seen_labels: set[str] = set()
        input_tags = {"input", "textarea"}
        input_roles = {"textbox", "searchbox"}

        for mark in snapshot.marks:
            if mark.tag not in input_tags and mark.role not in input_roles and not mark.input_type:
                continue

            label = self._get_candidate_label(mark)
            label = self._compact_text(label) if label else ""
            if not label:
                label = "[input]"

            label_key = f"{label.lower()}-{mark.mark_id}"
            if label_key in seen_labels:
                continue
            seen_labels.add(label_key)

            score = 0.5
            if mark.input_type:
                score += 0.2
            if mark.placeholder or mark.aria_label:
                score += 0.1
            if mark.tag in input_tags:
                score += 0.2

            candidates.append((score, mark, label))

        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1].center_normalized[1],
                item[1].center_normalized[0],
            )
        )
        return candidates

    def _build_input_candidates_text(
        self,
        snapshot: "SoMSnapshot",
        max_candidates: int = 20,
    ) -> tuple[str, int]:
        candidates = self._collect_input_candidates(snapshot)
        if not candidates:
            return "无", 0

        lines = []
        for _, mark, label in candidates[:max_candidates]:
            cx, cy = mark.center_normalized
            role_text = mark.role or "none"
            input_type = mark.input_type or "text"
            lines.append(
                f"- [{mark.mark_id}] {label} "
                f"(tag={mark.tag} role={role_text} type={input_type} "
                f"@{cx:.2f},{cy:.2f})"
            )

        return "\n".join(lines), len(lines)

    def get_clickable_candidate_ids(
        self,
        snapshot: "SoMSnapshot",
        exclude_ids: set[int] | None = None,
        max_candidates: int = 20,
    ) -> list[int]:
        candidates = self._collect_clickable_candidates(snapshot)
        if not candidates:
            return []

        filtered = []
        for _, mark, _label in candidates:
            if exclude_ids and mark.mark_id in exclude_ids:
                continue
            filtered.append(mark.mark_id)

        return filtered[:max_candidates]

    async def decide_navigation(
        self,
        snapshot: "SoMSnapshot",
        screenshot_base64: str,
        field: FieldDefinition,
        nav_steps_count: int = 0,
        nav_steps_summary: str | None = None,
        scroll_info: "ScrollInfo | None" = None,
        page_text_hit: bool | None = None,
    ) -> dict | None:
        """
        决定导航操作

        根据当前页面状态和目标字段，决定下一步操作：
        - extract: 已找到目标字段（found=true）
        - click: 点击元素展开更多
        - scroll: 向下滚动
        - extract: 字段不存在（found=false）

        Args:
            snapshot: SoM 快照
            screenshot_base64: 截图 Base64
            field: 目标字段定义
            nav_steps_count: 已执行的导航步数
            scroll_info: 滚动状态信息

        Returns:
            决策结果字典，包含 action 和相关参数
        """
        current_url = self.page.url

        logger.info(f"[FieldDecider] 导航决策 - 字段: {field.name}")
        logger.info(f"[FieldDecider] 当前页面: {current_url[:80]}...")
        logger.info(f"[FieldDecider] 已执行步数: {nav_steps_count}")

        # 构建滚动状态描述
        scroll_status = "无滚动信息"
        if scroll_info:
            scroll_status = f"滚动进度: {scroll_info.scroll_percent:.0%}"
            if scroll_info.is_at_bottom:
                scroll_status += "（已到底部）"
            elif scroll_info.is_at_top:
                scroll_status += "（在顶部）"

        page_text_hit_text = "未知"
        if page_text_hit is True:
            page_text_hit_text = "是"
        elif page_text_hit is False:
            page_text_hit_text = "否"

        # 加载 Prompt
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="navigate_to_field_system_prompt",
        )

        clickable_candidates_text, clickable_candidates_count = (
            self._build_clickable_candidates_text(snapshot)
        )
        input_candidates_text, input_candidates_count = self._build_input_candidates_text(snapshot)

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="navigate_to_field_user_message",
            variables={
                "field_name": field.name,
                "field_description": field.description,
                "field_example": field.example or "",
                "current_url": current_url,
                "nav_steps_count": nav_steps_count,
                "nav_steps_summary": nav_steps_summary or "无",
                "scroll_status": scroll_status,
                "clickable_candidates": clickable_candidates_text,
                "clickable_candidates_count": clickable_candidates_count,
                "input_candidates": input_candidates_text,
                "input_candidates_count": input_candidates_count,
                "page_text_hit": page_text_hit_text,
            },
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

        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            logger.info(f"[FieldDecider] 响应: {response_text[:150]}...")

            message = self._parse_response_json(response_text)
            if message:
                action = message.get("action")
                args = message.get("args") if isinstance(message.get("args"), dict) else {}

                if action == "extract":
                    kind = str(args.get("kind") or "").lower()
                    if kind and kind != "field":
                        logger.info(f"[FieldDecider] kind 不匹配: {kind}")
                        return None
                    field_name = args.get("field_name")
                    if field_name and not self._field_names_match(field_name, field.name):
                        logger.info(
                            f"[FieldDecider] 字段名不匹配: '{field_name}' != '{field.name}'"
                        )
                        return None

                logger.info(f"[FieldDecider] 决策: {action}")
                return message
            logger.info("[FieldDecider] 响应中未找到 JSON")
        except Exception as e:
            logger.info(f"[FieldDecider] 决策失败: {e}")
            import traceback

            traceback.print_exc()

        return None

    async def extract_field_text(
        self,
        screenshot_base64: str,
        field: FieldDefinition,
    ) -> dict | None:
        """
        让 LLM 识别并输出字段文本

        Args:
            screenshot_base64: 截图 Base64
            field: 目标字段定义

        Returns:
            提取结果字典，包含 found, field_value, confidence 等
        """
        logger.info(f"[FieldDecider] 提取字段文本 - 字段: {field.name}")

        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="extract_field_text_system_prompt",
        )

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="extract_field_text_user_message",
            variables={
                "field_name": field.name,
                "field_description": field.description,
                "field_data_type": field.data_type,
                "field_example": field.example or "",
            },
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

        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            logger.info(f"[FieldDecider] 响应: {response_text[:150]}...")

            message = self._parse_response_json(response_text)
            if message:
                action = message.get("action")
                args = message.get("args") if isinstance(message.get("args"), dict) else {}

                if action != "extract":
                    logger.info(f"[FieldDecider] 非 extract 动作，忽略: {action}")
                    return None

                kind = str(args.get("kind") or "").lower()
                if kind and kind != "field":
                    logger.info(f"[FieldDecider] kind 不匹配: {kind}")
                    return None

                field_name = args.get("field_name")
                if field_name and not self._field_names_match(field_name, field.name):
                    logger.info(f"[FieldDecider] 字段名不匹配: '{field_name}' != '{field.name}'")
                    return None

                found = coerce_bool(args.get("found"))
                if found is None:
                    found = bool(args.get("field_value") or args.get("field_text"))
                if found:
                    value = args.get("field_value") or args.get("field_text") or ""
                    logger.info(f"[FieldDecider] 提取到值: {str(value)[:50]}...")
                else:
                    logger.info("[FieldDecider] 未找到字段")
                return message
        except Exception as e:
            logger.info(f"[FieldDecider] 提取失败: {e}")

        return None

    async def select_correct_match(
        self,
        screenshot_base64: str,
        field: FieldDefinition,
        candidates: list[dict],
    ) -> dict | None:
        """
        从多个候选中选择正确的匹配

        Args:
            screenshot_base64: 截图 Base64（候选元素已用 SoM 标注）
            field: 目标字段定义
            candidates: 候选列表，每个元素包含 mark_id 和 text

        Returns:
            选择结果字典，包含 selected_mark_id 和 reasoning
        """
        logger.info(f"[FieldDecider] 多候选消歧 - 字段: {field.name}, 候选数: {len(candidates)}")

        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_match_system_prompt",
        )

        # 构建候选列表文本
        candidates_text = "\n".join([f"- **[{c['mark_id']}]** {c['text']}" for c in candidates])

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_match_user_message",
            variables={
                "field_name": field.name,
                "field_description": field.description,
                "candidates": candidates,
            },
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

        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            logger.info(f"[FieldDecider] 响应: {response_text[:150]}...")

            message = self._parse_response_json(response_text)
            if message:
                action = message.get("action")
                if action != "select":
                    logger.info(f"[FieldDecider] 非 select 动作，忽略: {action}")
                    return None

                args = message.get("args") if isinstance(message.get("args"), dict) else {}
                selected = args.get("selected_mark_id")
                if selected is None:
                    items = args.get("items") or []
                    if items and isinstance(items[0], dict):
                        selected = items[0].get("mark_id")
                if selected is None:
                    selected = args.get("mark_id")
                logger.info(f"[FieldDecider] 选择: mark_id={selected}")
                return message
        except Exception as e:
            logger.info(f"[FieldDecider] 消歧失败: {e}")

        return None

    async def check_field_in_page_text(
        self,
        page_text: str,
        field: FieldDefinition,
    ) -> bool:
        """
        检查页面文本中是否包含目标字段的相关内容

        这是一个快速检查，用于在调用视觉 LLM 之前预判字段是否存在。

        Args:
            page_text: 页面的 innerText
            field: 目标字段定义

        Returns:
            是否可能包含目标字段
        """
        # 简单的关键词匹配
        keywords = [field.name]
        if field.description:
            # 从描述中提取可能的关键词
            keywords.extend(field.description.split()[:3])

        cleaned_text = page_text
        if "<" in cleaned_text:
            cleaned_text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", cleaned_text)
            cleaned_text = re.sub(r"(?s)<[^>]+>", " ", cleaned_text)
        cleaned_text = re.sub(r"\s+", " ", cleaned_text)

        page_text_lower = cleaned_text.lower()
        for keyword in keywords:
            if keyword.lower() in page_text_lower:
                return True

        return False
