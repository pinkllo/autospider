"""字段提取 LLM 决策器

负责调用 LLM 进行字段提取相关的决策：
- 导航决策：判断目标字段是否可见
- 字段文本提取：识别并提取字段值
- 多候选消歧：从多个匹配中选择正确的
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from ..extractor.llm.prompt_template import render_template
from ..common.protocol import (
    parse_protocol_message,
    protocol_to_legacy_field_extract_result,
    protocol_to_legacy_field_nav_decision,
    protocol_to_legacy_selected_mark,
)
from .models import FieldDefinition

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..extractor.llm import LLMDecider
    from ..common.types import ElementMark, SoMSnapshot, ScrollInfo


# Prompt 模板文件路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).resolve().parents[3] / "prompts" / "field_extractor.yaml")


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

    def _strip_code_fences(self, text: str) -> str:
        if "```" not in text:
            return text
        cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
        return cleaned.replace("```", "").strip()

    def _extract_json_block(self, text: str) -> str | None:
        match = re.search(r"\{[\s\S]*\}", text)
        return match.group(0) if match else None

    def _salvage_response(self, text: str) -> dict | None:
        data: dict = {}

        action_match = re.search(r'"action"\s*:\s*"?(?P<action>[a-zA-Z_]+)', text)
        if action_match:
            data["action"] = action_match.group("action")

        mark_id_match = re.search(r'"mark_id"\s*:\s*"?(?P<mark_id>\d+)', text)
        if mark_id_match:
            data["mark_id"] = mark_id_match.group("mark_id")

        selected_match = re.search(r'"selected_mark_id"\s*:\s*"?(?P<selected>\d+)', text)
        if selected_match:
            data["selected_mark_id"] = selected_match.group("selected")

        found_match = re.search(r'"found"\s*:\s*(true|false)', text, re.IGNORECASE)
        if found_match:
            data["found"] = found_match.group(1).lower() == "true"

        confidence_match = re.search(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)', text)
        if confidence_match:
            try:
                data["confidence"] = float(confidence_match.group(1))
            except ValueError:
                pass

        for key in ["field_value", "field_text", "reasoning", "location_description", "target_text"]:
            value_match = re.search(rf'"{key}"\s*:\s*"([^"]*)', text)
            if value_match:
                data[key] = value_match.group(1)

        for key in ["text", "key"]:
            value_match = re.search(rf'"{key}"\s*:\s*"([^"]*)', text)
            if value_match:
                data[key] = value_match.group(1)

        return data or None

    def _parse_response_json(self, response_text: str) -> dict | None:
        # 修改原因：协议兼容统一收口到 common.protocol，避免各处重复补丁。
        return parse_protocol_message(response_text)

    def _compact_text(self, text: str, max_len: int = 60) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) > max_len:
            return cleaned[: max_len - 3] + "..."
        return cleaned

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
            if (
                mark.tag not in input_tags
                and mark.role not in input_roles
                and not mark.input_type
            ):
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
        - found_field: 已找到目标字段
        - click: 点击元素展开更多
        - scroll_down: 向下滚动
        - field_not_exist: 字段不存在
        
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
        
        print(f"[FieldDecider] 导航决策 - 字段: {field.name}")
        print(f"[FieldDecider] 当前页面: {current_url[:80]}...")
        print(f"[FieldDecider] 已执行步数: {nav_steps_count}")
        
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
        input_candidates_text, input_candidates_count = (
            self._build_input_candidates_text(snapshot)
        )
        
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
            }
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
            ]),
        ]
        
        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            print(f"[FieldDecider] 响应: {response_text[:150]}...")

            data = self._parse_response_json(response_text)
            if data:
                # 兼容：统一输出结构（action/args）→ 字段导航旧结构
                data = protocol_to_legacy_field_nav_decision(data, field.name)
                print(f"[FieldDecider] 决策: {data.get('action')}")
                return data
            print(f"[FieldDecider] 响应中未找到 JSON")
        except Exception as e:
            print(f"[FieldDecider] 决策失败: {e}")
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
        print(f"[FieldDecider] 提取字段文本 - 字段: {field.name}")
        
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
            }
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
            ]),
        ]
        
        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            print(f"[FieldDecider] 响应: {response_text[:150]}...")

            data = self._parse_response_json(response_text)
            if data:
                # 兼容：统一输出结构（action/args）→ 字段提取旧结构
                data = protocol_to_legacy_field_extract_result(data, field.name)
                if data.get("found"):
                    print(f"[FieldDecider] 提取到值: {data.get('field_value', '')[:50]}...")
                else:
                    print(f"[FieldDecider] 未找到字段")
                return data
        except Exception as e:
            print(f"[FieldDecider] 提取失败: {e}")
        
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
        print(f"[FieldDecider] 多候选消歧 - 字段: {field.name}, 候选数: {len(candidates)}")
        
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_match_system_prompt",
        )
        
        # 构建候选列表文本
        candidates_text = "\n".join([
            f"- **[{c['mark_id']}]** {c['text']}"
            for c in candidates
        ])
        
        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_match_user_message",
            variables={
                "field_name": field.name,
                "field_description": field.description,
                "candidates": candidates,
            }
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
            ]),
        ]
        
        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            print(f"[FieldDecider] 响应: {response_text[:150]}...")

            data = self._parse_response_json(response_text)
            if data:
                # 兼容：统一输出结构（action/args）→ selected_mark_id 旧结构
                data = protocol_to_legacy_selected_mark(data)
                print(f"[FieldDecider] 选择: mark_id={data.get('selected_mark_id')}")
                return data
        except Exception as e:
            print(f"[FieldDecider] 消歧失败: {e}")
        
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
            cleaned_text = re.sub(
                r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", cleaned_text
            )
            cleaned_text = re.sub(r"(?s)<[^>]+>", " ", cleaned_text)
        cleaned_text = re.sub(r"\s+", " ", cleaned_text)

        page_text_lower = cleaned_text.lower()
        for keyword in keywords:
            if keyword.lower() in page_text_lower:
                return True
        
        return False
