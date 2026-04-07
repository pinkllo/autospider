"""任务澄清器：将自然语言多轮对话转换为可执行爬取配置。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...domain.chat import ClarificationResult, ClarifiedTask, DialogueMessage
from ...domain.fields import FieldDefinition
from ..config import config
from ..llm_contracts import validate_task_clarifier_payload
from ..protocol import parse_json_dict_from_llm
from ..utils.paths import get_prompt_path
from ..utils.prompt_template import render_template
from ..validators import validate_url
from .trace_logger import append_llm_trace
from autospider.common.logger import get_logger

# 获取日志记录器
logger = get_logger(__name__)

# 获取提示词模板路径和允许的字段类型
PROMPT_TEMPLATE_PATH = get_prompt_path("task_clarifier.yaml")
ALLOWED_FIELD_TYPES = {"text", "number", "date", "url"}


class TaskClarifier:
    """基于 LLM 的多轮任务澄清器，负责将模糊的对话转化为清晰的爬虫配置。"""

    def __init__(self):
        """初始化澄清器，读取 LLM 相关的配置参数。"""
        # 优先使用专门的 planner 配置，若无则使用通用的 llm 配置
        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model

        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        # 初始化 ChatOpenAI 客户端，配置为返回 JSON 对象
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=0.1,
            max_tokens=2048,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": config.llm.enable_thinking},
        )

    async def clarify(
        self,
        history: list[DialogueMessage],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> ClarificationResult:
        """
        基于当前会话历史返回下一步澄清结果。
        
        Args:
            history: 对话历史列表。
            available_skills: 当前 URL 可用的 skills metadata，仅用于 trace。
            selected_skills: 本轮被 selector 选中的 skills metadata，仅用于 trace。
            selected_skills_context: 选中的 SKILL.md 正文上下文。
            
        Returns:
            ClarificationResult: 澄清结果，指示是继续提问、生成任务还是拒绝。
        """
        # 格式化对话历史供模型参考
        conversation_history = self._format_history(history)
        selected_context = (
            str(selected_skills_context or "").strip()
            or "当前未选择任何站点 skills。"
        )
        
        # 渲染系统提示词和用户提示词
        system_prompt = render_template(PROMPT_TEMPLATE_PATH, section="system_prompt")
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="user_prompt",
            variables={
                "conversation_history": conversation_history,
                "selected_skills_context": selected_context,
            },
        )

        # 调用 LLM 获取响应
        response = await self.llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        # 解析 LLM 返回的 JSON 格式内容
        raw_payload = parse_json_dict_from_llm(str(response.content)) or {}
        payload, validation_errors = validate_task_clarifier_payload(raw_payload)
        if raw_payload and validation_errors:
            logger.warning(
                "[TaskClarifier] LLM payload validation failed: %s",
                "; ".join(validation_errors),
            )
        result = self._normalize_result(payload, history)
        append_llm_trace(
            component="task_clarifier",
            payload={
                "model": config.llm.planner_model or config.llm.model,
                "input": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "conversation_history": conversation_history,
                    "available_skills": available_skills or [],
                    "selected_skills": selected_skills or [],
                    "selected_skill_paths": [
                        str(item.get("path") or "")
                        for item in list(selected_skills or [])
                        if isinstance(item, dict)
                    ],
                    "selected_skills_context": selected_context,
                },
                "output": {
                    "raw_response": str(response.content),
                    "parsed_payload": raw_payload,
                    "validated_payload": payload,
                    "payload_validation_errors": validation_errors,
                    "normalized_result": {
                        "status": result.status,
                        "intent": result.intent,
                        "confidence": result.confidence,
                        "next_question": result.next_question,
                        "reason": result.reason,
                        "has_task": result.task is not None,
                        "task_overrides": {
                            "max_pages": result.task.max_pages if result.task else None,
                            "target_url_count": result.task.target_url_count if result.task else None,
                            "consumer_concurrency": result.task.consumer_concurrency if result.task else None,
                            "field_explore_count": result.task.field_explore_count if result.task else None,
                            "field_validate_count": result.task.field_validate_count if result.task else None,
                        },
                    },
                },
            },
        )
        return result

    def _format_history(self, history: list[DialogueMessage]) -> str:
        """将对话历史对象转换为字符串列表，供 Prompt 使用。保留最近的 20 条记录。"""
        lines: list[str] = []
        for index, message in enumerate(history[-20:], start=1):
            role = "用户" if message.role == "user" else "助手"
            lines.append(f"{index}. {role}: {message.content.strip()}")
        return "\n".join(lines) if lines else "（暂无历史）"

    def _normalize_result(
        self,
        payload: dict[str, Any],
        history: list[DialogueMessage],
    ) -> ClarificationResult:
        """
        对模型返回的数据进行标准化处理，补全默认值并根据逻辑修正状态。
        
        Args:
            payload: LLM 返回的原始字典数据。
            history: 对话历史列表，用于判断是否为硬拒绝。
        """
        status = str(payload.get("status") or "need_clarification").strip().lower()
        if status not in {"need_clarification", "ready", "reject"}:
            status = "need_clarification"

        intent = str(payload.get("intent") or "").strip()
        confidence = _to_float(payload.get("confidence"), 0.0)
        next_question = str(payload.get("next_question") or "").strip()
        reason = str(payload.get("rejection_reason") or "").strip()

        task: ClarifiedTask | None = None
        if status == "ready":
            # 尝试根据载荷构建任务配置
            task = self._build_task(payload)
            # 如果关键信息缺失，则回退为需要澄清状态
            if task is None:
                status = "need_clarification"
                next_question = (
                    next_question
                    or "我还缺少可执行信息。请提供列表页 URL，并确认希望提取的字段。"
                )

        if status == "reject" and not self._is_hard_reject(reason, history):
            status = "need_clarification"
            reason = ""
            if not next_question:
                next_question = self._build_fallback_question(history)

        # 确保状态为需要澄清时必须有问题，拒绝时必须有原因
        if status == "need_clarification" and not next_question:
            next_question = "请补充你要采集的网站列表页 URL，以及你最关心的字段。"

        if status == "reject" and not reason:
            reason = "该需求暂时无法安全执行。"

        return ClarificationResult(
            status=status,
            intent=intent,
            confidence=confidence,
            next_question=next_question,
            reason=reason,
            task=task,
        )

    def _is_hard_reject(self, reason: str, history: list[DialogueMessage]) -> bool:
        """仅对明显违规/恶意场景保留 reject。"""
        haystack = " ".join(
            [
                reason,
                *[message.content for message in history[-10:]],
            ]
        ).lower()
        hard_keywords = [
            "违法",
            "非法",
            "攻击",
            "入侵",
            "破解",
            "盗号",
            "敏感隐私",
            "个人隐私",
            "恶意",
            "诈骗",
            "violence",
            "exploit",
            "hack",
            "phishing",
            "malware",
        ]
        return any(keyword in haystack for keyword in hard_keywords)

    def _build_fallback_question(self, history: list[DialogueMessage]) -> str:
        """当模型误拒绝时，生成可执行的兜底追问。"""
        return (
            "我不会因为缺少 URL 直接拒绝任务。请在以下两种方式中二选一：\n"
            "A. 直接提供目标站的列表页 URL；\n"
            "B. 从搜索引擎起步（例如 https://www.baidu.com ），由系统先搜索再进入目标站。\n"
            "如果页面需要登录，系统支持人工登录接管后继续执行。\n"
            "请回复 A 或 B；若选 B，请同时提供搜索关键词。"
        )

    def _build_task(self, payload: dict[str, Any]) -> ClarifiedTask | None:
        """
        从载荷中提取并构建 ClarifiedTask 对象。
        
        Args:
            payload: LLM 返回的原始字典数据。
            
        Returns:
            ClarifiedTask: 构建成功的任务对象；若核心参数缺失或 URL 无效则返回 None。
        """
        list_url = str(payload.get("list_url") or "").strip()
        task_description = str(payload.get("task_description") or "").strip()
        fields = self._parse_fields(payload.get("fields"))
        max_pages = _to_int(payload.get("max_pages"))
        target_url_count = _to_int(payload.get("target_url_count"))
        consumer_concurrency = _to_int(payload.get("consumer_concurrency"))
        field_explore_count = _to_int(payload.get("field_explore_count"))
        field_validate_count = _to_int(payload.get("field_validate_count"))
        intent = str(payload.get("intent") or "").strip()

        # 检查必填项：URL、任务描述和字段
        if not list_url or not task_description or not fields:
            return None

        # 验证 URL 格式是否正确
        try:
            list_url = validate_url(list_url)
        except Exception:
            logger.info("[TaskClarifier] list_url 非法，回退到继续澄清")
            return None

        return ClarifiedTask(
            intent=intent,
            list_url=list_url,
            task_description=task_description,
            fields=fields,
            max_pages=max_pages,
            target_url_count=target_url_count,
            consumer_concurrency=consumer_concurrency,
            field_explore_count=field_explore_count,
            field_validate_count=field_validate_count,
        )

    def _parse_fields(self, value: Any) -> list[FieldDefinition]:
        """
        将列表数据解析为字段定义对象列表。
        
        Args:
            value: 原始字段数据列表。
            
        Returns:
            list[FieldDefinition]: 解析后的字段定义列表。
        """
        if not isinstance(value, list):
            return []

        fields: list[FieldDefinition] = []
        for item in value:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            if not name or not description:
                continue

            # 校验并归一化数据类型
            raw_type = str(item.get("data_type") or "text").strip().lower()
            data_type = raw_type if raw_type in ALLOWED_FIELD_TYPES else "text"
            
            # 处理示例数据，空字符串视为 None
            example_raw = item.get("example")
            example = str(example_raw).strip() if example_raw is not None else None
            if example == "":
                example = None

            fields.append(
                FieldDefinition(
                    name=name,
                    description=description,
                    required=bool(item.get("required", True)),
                    data_type=data_type,
                    example=example,
                )
            )
        return fields


def _to_int(value: Any) -> int | None:
    """类型安全转换为正整数。"""
    try:
        if value is None:
            return None
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _to_float(value: Any, default: float) -> float:
    """类型安全转换为浮点数，失败则返回默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
