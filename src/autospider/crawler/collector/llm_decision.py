"""LLM 决策模块"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from ...common.utils.prompt_template import render_template
from ...common.logger import get_logger
from ...common.som.text_first import disambiguate_mark_id_by_text as _disambiguate_mark_id_by_text
from ...common.protocol import parse_protocol_message
from ...common.utils.paths import get_prompt_path

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ...common.llm import LLMDecider
    from ...common.types import SoMSnapshot, ElementMark


# Prompt 模板文件路径
PROMPT_TEMPLATE_PATH = get_prompt_path("url_collector.yaml")
logger = get_logger(__name__)


class LLMDecisionMaker:
    """LLM 决策制定器，负责调用 LLM 进行决策"""

    def __init__(
        self,
        page: "Page",
        decider: "LLMDecider",
        task_description: str,
        collected_urls: list[str],
        visited_detail_urls: set[str],
        list_url: str,
    ):
        self.page = page
        self.decider = decider
        self.task_description = task_description
        self.collected_urls = collected_urls
        self.visited_detail_urls = visited_detail_urls
        self.list_url = list_url

    async def ask_for_decision(
        self,
        snapshot: "SoMSnapshot",
        screenshot_base64: str = "",
        validation_feedback: str = "",
    ) -> dict | None:
        """让视觉 LLM 决定如何获取详情页 URL

        Args:
            snapshot: SoM 快照
            screenshot_base64: 截图的 base64 编码
            validation_feedback: 验证失败的反馈信息（用于让 LLM 重新选择）
        """
        current_url = self.page.url

        logger.info("[LLM] 当前页面: %s...", current_url[:80])
        logger.info("[LLM] 可交互元素数量: %s", len(snapshot.marks))
        logger.info("[LLM] 截图大小: %s 字符", len(screenshot_base64))
        if validation_feedback:
            logger.info("[LLM] 包含验证反馈信息（重新选择）")

        # 使用模板引擎加载 system_prompt
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="ask_llm_decision_system_prompt",
        )

        # 已收集的 URL（用于避免重复）
        collected_urls_str = (
            "\n".join([f"- {url}" for url in list(self.collected_urls)[:10]])
            if self.collected_urls
            else "暂无"
        )

        # 使用模板引擎加载 user_message
        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="ask_llm_decision_user_message",
            variables={
                "task_description": self.task_description,
                "current_url": current_url,
                "visited_count": len(self.visited_detail_urls),
                "collected_urls_str": collected_urls_str,
            },
        )

        # 如果有验证反馈，追加到用户消息中
        if validation_feedback:
            user_message += f"\n\n## ⚠️ 上一次选择的 mark_id 验证失败\n{validation_feedback}\n\n请仔细核对截图中红色边框右上角的白色数字编号，重新选择正确的 mark_id。"

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
            logger.info("[LLM] 调用视觉 LLM 进行决策...")
            # 使用 decider 的 LLM（视觉模型）
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            logger.info("[LLM] 响应前100字符: %s...", response_text[:100])

            message = parse_protocol_message(response_text)
            if message:
                args = message.get("args") if isinstance(message.get("args"), dict) else {}
                reasoning = args.get("reasoning") or message.get("thinking") or "N/A"
                logger.info("[LLM] 决策: %s", message.get("action"))
                logger.info("[LLM] 理由: %s...", str(reasoning)[:100])
                return message

            logger.warning("[LLM] 响应中未找到 JSON: %s", response_text[:200])
        except json.JSONDecodeError as e:
            logger.warning("[LLM] JSON 解析失败: %s", e)
            logger.warning(
                "[LLM] 原始响应: %s",
                response_text[:300] if "response_text" in locals() else "N/A",
            )
        except Exception as e:
            logger.error("[LLM] 决策失败: %s", e)
            import traceback

            traceback.print_exc()

        return None

    async def disambiguate_mark_id_by_text(
        self,
        candidates: list["ElementMark"],
        target_text: str,
        max_retries: int = 1,
    ) -> int | None:
        """当文本命中多个候选时，重新框选这些候选让 LLM 重选

        修改原因：消歧逻辑需要在全项目复用，因此下沉到 `common/som/text_first.py` 统一实现。
        """
        return await _disambiguate_mark_id_by_text(
            page=self.page,
            llm=self.decider.llm,
            candidates=candidates,
            target_text=target_text,
            max_retries=max_retries,
        )

    async def extract_jump_widget_with_llm(
        self, snapshot: "SoMSnapshot", screenshot_base64: str
    ) -> dict | None:
        """使用 LLM 视觉识别页码跳转控件（输入框 + 确定按钮）"""

        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="jump_widget_llm_system_prompt",
        )

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="jump_widget_llm_user_message",
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

            message = parse_protocol_message(response_text)
            if message:
                return message
        except Exception as e:
            logger.warning("[Extract-JumpWidget-LLM] LLM 识别失败: %s", e)

        return None

    async def extract_pagination_with_llm(
        self, snapshot: "SoMSnapshot", screenshot_base64: str
    ) -> dict | None:
        """使用 LLM 视觉识别分页控件并提取 xpath"""

        # 使用模板引擎加载 system_prompt
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="pagination_llm_system_prompt",
        )

        # 使用模板引擎加载 user_message
        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="pagination_llm_user_message",
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

            message = parse_protocol_message(response_text)
            if message:
                return message
        except Exception as e:
            logger.warning("[Extract-Pagination-LLM] LLM 识别失败: %s", e)

        return None
