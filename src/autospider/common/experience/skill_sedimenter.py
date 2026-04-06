"""经验沉淀器 — 将完成的采集任务转化为标准 Agent Skills 格式。

核心流程：
1. 从任务结果中提取结构化硬数据（XPath、导航步骤等）—— 零成本，纯代码
2. 汇总多子任务的错误轨迹和提取结果 —— Map-Reduce 合并
3. 调取一次 LLM 生成软经验总结 —— 仅一次调用
4. 产出结构化 SkillDocument 并统一交给 SkillStore 渲染/合并/保存
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import config
from ..logger import get_logger
from .skill_store import (
    SkillDocument,
    SkillFieldRule,
    SkillRuleData,
    SkillStore,
)

logger = get_logger(__name__)


def _extract_domain(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


@dataclass(frozen=True, slots=True)
class SkillSedimentationPayload:
    list_url: str
    task_description: str
    fields: list[dict[str, Any]]
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    subtask_names: list[str] = field(default_factory=list)
    plan_knowledge: str = ""
    status: str = "validated"


class SkillSedimenter:
    """经验沉淀器。

    将 Pipeline 执行产物转化为结构化 SkillDocument，并交给 SkillStore 保存。
    """

    def __init__(self, skills_dir: str | Path | None = None):
        self.store = SkillStore(skills_dir=skills_dir)

    def sediment_from_pipeline_result(
        self,
        payload: SkillSedimentationPayload,
    ) -> Path | None:
        """从单个 Pipeline 运行结果沉淀 Skill。

        Returns:
            生成的 SKILL.md 文件路径，如果沉淀失败则返回 None
        """
        try:
            summary = dict(payload.summary or {})
            collection_config = dict(payload.collection_config or {})
            extraction_config = dict(payload.extraction_config or {})
            validation_failures = list(payload.validation_failures or [])

            success_count = int(summary.get("success_count", 0) or 0)
            if success_count <= 0:
                logger.debug("[SkillSedimenter] 任务无成功记录，跳过沉淀")
                return None

            domain = _extract_domain(payload.list_url)
            if not domain:
                logger.debug("[SkillSedimenter] 无法从 URL 提取域名，跳过沉淀")
                return None

            # 第一步：提取结构化规则层
            rules = self._build_rule_data(
                domain=domain,
                list_url=payload.list_url,
                task_description=payload.task_description,
                fields=payload.fields,
                collection_config=collection_config,
                extraction_config=extraction_config,
                summary=summary,
                subtask_names=payload.subtask_names,
                status=payload.status,
            )

            # 第二步：生成软经验总结
            insights = self._generate_insights(
                domain=domain,
                fields=payload.fields,
                extraction_config=extraction_config,
                validation_failures=validation_failures,
                summary=summary,
                plan_knowledge=payload.plan_knowledge,
            )

            # 第三步：产出结构化文档并统一保存
            document = self._build_skill_document(rules=rules, insights=insights)
            return self.store.save_document(domain, document)

        except Exception as exc:
            logger.debug("[SkillSedimenter] 沉淀失败（不影响主流程）: %s", exc)
            return None

    def sediment_from_subtask_results(
        self,
        *,
        list_url: str,
        task_description: str,
        fields: list[dict[str, Any]],
        subtask_results: list[dict[str, Any]],
        plan_knowledge: str = "",
    ) -> Path | None:
        """从多个子任务结果聚合沉淀为一个统一 Skill（Map-Reduce）。"""
        try:
            if not subtask_results:
                return None

            merged_xpaths = self._merge_subtask_xpaths(subtask_results, fields)
            merged_collection = self._merge_subtask_configs(subtask_results)
            merged_failures = self._merge_subtask_failures(subtask_results)
            subtask_names = [str(r.get("name", "")) for r in subtask_results if r.get("name")]

            total_success = sum(
                int(r.get("summary", {}).get("success_count", 0) or 0)
                for r in subtask_results
            )
            total_urls = sum(
                int(r.get("summary", {}).get("total_urls", 0) or 0)
                for r in subtask_results
            )
            merged_summary = {
                "success_count": total_success,
                "total_urls": total_urls,
            }

            if total_success <= 0:
                logger.debug("[SkillSedimenter] 所有子任务均无成功记录，跳过沉淀")
                return None

            return self.sediment_from_pipeline_result(
                SkillSedimentationPayload(
                    list_url=list_url,
                    task_description=task_description,
                    fields=fields,
                    collection_config=merged_collection,
                    extraction_config=merged_xpaths,
                    summary=merged_summary,
                    validation_failures=merged_failures,
                    subtask_names=subtask_names,
                    plan_knowledge=plan_knowledge,
                )
            )

        except Exception as exc:
            logger.debug("[SkillSedimenter] 子任务聚合沉淀失败: %s", exc)
            return None

    # ===== 内部方法 =====

    def _build_rule_data(
        self,
        *,
        domain: str,
        list_url: str,
        task_description: str,
        fields: list[dict[str, Any]],
        collection_config: dict[str, Any],
        extraction_config: dict[str, Any],
        summary: dict[str, Any],
        subtask_names: list[str] | None = None,
        status: str = "validated",
    ) -> SkillRuleData:
        """提取结构化规则层（纯代码逻辑，不用 LLM）。"""
        field_desc_map = {
            str(f.get("name", "")): str(f.get("description", ""))
            for f in fields
            if isinstance(f, dict) and f.get("name")
        }

        field_rules: dict[str, SkillFieldRule] = {}
        extraction_fields = extraction_config.get("fields", [])
        for ef in extraction_fields:
            if not isinstance(ef, dict):
                continue
            name = str(ef.get("name", ""))
            if not name:
                continue

            validated = bool(ef.get("xpath_validated"))
            field_rules[name] = SkillFieldRule(
                name=name,
                description=field_desc_map.get(name, ""),
                primary_xpath=str(ef.get("xpath") or "").strip(),
                fallback_xpaths=[
                    str(xpath).strip()
                    for xpath in ef.get("xpath_fallbacks", [])
                    if str(xpath).strip()
                ],
                confidence=0.9 if validated else 0.6,
                validated=validated,
                data_type=str(ef.get("data_type") or "text"),
                extraction_source=str(ef.get("extraction_source") or ""),
                fixed_value=str(ef.get("fixed_value") or ""),
            )

        nav_steps: list[dict[str, str]] = []
        for step in collection_config.get("nav_steps", []):
            if not isinstance(step, dict):
                continue
            nav_steps.append({
                "action": str(step.get("action", "")),
                "xpath": str(step.get("xpath") or step.get("target_xpath") or ""),
                "value": str(step.get("value") or ""),
                "description": str(step.get("description", "")),
            })

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        success_rate = round(success_count / max(total_urls, 1), 2)
        success_rate_text = ""
        if total_urls > 0:
            success_rate_text = f"{success_rate * 100:.0f}% ({success_count}/{total_urls})"

        jump_widget = collection_config.get("jump_widget_xpath")
        jump_input_selector = ""
        jump_button_selector = ""
        if isinstance(jump_widget, dict):
            jump_input_selector = str(jump_widget.get("input") or "")
            jump_button_selector = str(jump_widget.get("button") or "")

        return SkillRuleData(
            domain=domain,
            name=f"{domain} 站点采集",
            description=(
                f"{domain} 数据采集技能。"
                f"包含列表页导航、分页处理和字段提取的操作指南。"
                f"状态: {'已验证' if status == 'validated' else '草稿'}。"
            ),
            list_url=list_url,
            task_description=task_description,
            status=str(status or "draft"),
            success_rate=success_rate,
            success_rate_text=success_rate_text,
            detail_xpath=str(collection_config.get("common_detail_xpath") or ""),
            pagination_xpath=str(collection_config.get("pagination_xpath") or ""),
            jump_input_selector=jump_input_selector,
            jump_button_selector=jump_button_selector,
            nav_steps=nav_steps,
            subtask_names=subtask_names or [],
            fields=field_rules,
        )

    def _build_skill_document(
        self,
        *,
        rules: SkillRuleData,
        insights: str,
    ) -> SkillDocument:
        return SkillDocument(
            frontmatter={
                "name": rules.name,
                "description": rules.description,
            },
            title=f"# {rules.domain} 采集指南",
            rules=rules,
            insights_markdown=insights.strip(),
        )

    def _generate_insights(
        self,
        *,
        domain: str,
        fields: list[dict[str, Any]],
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
        plan_knowledge: str = "",
    ) -> str:
        """生成软经验总结。"""
        rule_based = self._rule_based_insights(
            domain=domain,
            fields=fields,
            extraction_config=extraction_config,
            validation_failures=validation_failures,
            summary=summary,
        )

        try:
            llm_insights = self._llm_insights(
                domain=domain,
                extraction_config=extraction_config,
                validation_failures=validation_failures,
                summary=summary,
                plan_knowledge=plan_knowledge,
            )
            if llm_insights:
                return llm_insights
        except Exception as exc:
            logger.debug("[SkillSedimenter] LLM 总结生成失败，使用规则总结: %s", exc)

        return rule_based

    def _rule_based_insights(
        self,
        *,
        domain: str,
        fields: list[dict[str, Any]],
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str:
        """基于规则生成基础经验总结（无需 LLM）。"""
        parts: list[str] = []

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)

        # 站点特征
        if total_urls > 0:
            rate = success_count / total_urls * 100
            parts.append(f"**站点特征**\n本站成功率 {rate:.0f}% ({success_count}/{total_urls})。")

        # 已知问题
        if validation_failures:
            failure_reasons: Counter[str] = Counter()
            for fail in validation_failures:
                for f in fail.get("fields", []):
                    if f.get("error"):
                        failure_reasons[str(f["error"])] += 1
            if failure_reasons:
                problem_lines = [f"- {reason}（出现 {count} 次）" for reason, count in failure_reasons.most_common(5)]
                parts.append("**避坑指南**\n" + "\n".join(problem_lines))
            else:
                parts.append("**避坑指南**\n暂无已知问题。")
        else:
            parts.append("**避坑指南**\n暂无已知问题。")

        return "\n\n".join(parts)

    def _llm_insights(
        self,
        *,
        domain: str,
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
        plan_knowledge: str = "",
    ) -> str | None:
        """调用 LLM 生成高质量的经验总结。仅一次调用。"""
        if not config.llm.api_key:
            return None

        context_parts: list[str] = []
        context_parts.append(f"站点域名: {domain}")

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        context_parts.append(f"成功率: {success_count}/{total_urls}")

        if plan_knowledge:
            context_parts.append(f"规划发现过程记录：\n{plan_knowledge[:2000]}")

        ext_fields = extraction_config.get("fields", [])
        if ext_fields:
            field_lines = []
            for ef in ext_fields:
                if not isinstance(ef, dict):
                    continue
                name = ef.get("name", "")
                xpath = ef.get("xpath", "")
                validated = ef.get("xpath_validated", False)
                fallbacks = ef.get("xpath_fallbacks", [])
                field_lines.append(
                    f"  - {name}: xpath={xpath}, validated={validated}, "
                    f"fallbacks={len(fallbacks)}个"
                )
            context_parts.append("字段提取结果:\n" + "\n".join(field_lines))

        if validation_failures:
            fail_summary: list[str] = []
            for fail in validation_failures[:5]:
                url = str(fail.get("url", ""))[:60]
                failed_fields = [
                    f.get("field_name", "")
                    for f in fail.get("fields", [])
                    if f.get("error")
                ]
                if failed_fields:
                    fail_summary.append(f"  - {url}... 失败字段: {', '.join(failed_fields)}")
            if fail_summary:
                context_parts.append("校验失败记录:\n" + "\n".join(fail_summary))

        context = "\n".join(context_parts)

        prompt = (
            f"你是一名首席爬虫工程师。你刚完成了对 {domain} 的数据采集。\n"
            f"以下是本次运行的关键信息：\n\n{context}\n\n"
            f"请基于以上信息，写出简短的站点采集经验，包含以下部分：\n"
            f"1. **站点特征** — 2-3 句话总结站点的技术特征\n"
            f"2. **避坑指南** — 如有失败记录，针对性给出建议；如无失败，写'暂无已知问题'\n"
            f"3. **优化建议** — 并发度、延迟等策略性建议\n\n"
            f"要求极其简洁，总共不超过 200 字。每部分用 **加粗** 标题开头。\n"
            f"只输出纯文本内容，不要添加一级或二级标题，不要多余解释。"
        )

        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage

            llm = ChatOpenAI(
                api_key=config.llm.api_key,
                base_url=config.llm.api_base,
                model=config.llm.model,
                temperature=0.3,
                max_tokens=1024,
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            if response and response.content:
                return str(response.content).strip()
        except Exception as exc:
            logger.debug("[SkillSedimenter] LLM 调用失败: %s", exc)

        return None

    # ===== Map-Reduce 合并方法 =====

    def _merge_subtask_xpaths(
        self,
        subtask_results: list[dict[str, Any]],
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Map-Reduce: 合并多个子任务的 XPath（投票机制）。"""
        field_xpaths: dict[str, list[str]] = {}
        field_fallbacks: dict[str, list[str]] = {}
        field_validated: dict[str, list[bool]] = {}

        for result in subtask_results:
            ext_config = result.get("extraction_config", {})
            for ef in ext_config.get("fields", []):
                if not isinstance(ef, dict):
                    continue
                name = str(ef.get("name", ""))
                xpath = ef.get("xpath")
                if name and xpath:
                    field_xpaths.setdefault(name, []).append(xpath)
                    for fb in ef.get("xpath_fallbacks", []):
                        field_fallbacks.setdefault(name, []).append(fb)
                    field_validated.setdefault(name, []).append(
                        bool(ef.get("xpath_validated"))
                    )

        merged_fields: list[dict[str, Any]] = []
        field_map = {str(f.get("name", "")): f for f in fields if isinstance(f, dict)}

        for name, xpaths in field_xpaths.items():
            counter = Counter(xpaths)
            top_xpath, top_count = counter.most_common(1)[0]

            all_fallbacks = list(field_fallbacks.get(name, []))
            unique_fallbacks = []
            seen = {top_xpath}
            for fb in all_fallbacks:
                if fb not in seen:
                    seen.add(fb)
                    unique_fallbacks.append(fb)
            for xpath, _ in counter.most_common():
                if xpath not in seen:
                    seen.add(xpath)
                    unique_fallbacks.append(xpath)

            validations = field_validated.get(name, [])
            validated = sum(validations) > len(validations) / 2 if validations else False

            orig_field = field_map.get(name, {})
            merged_fields.append({
                "name": name,
                "description": orig_field.get("description", ""),
                "xpath": top_xpath,
                "xpath_fallbacks": unique_fallbacks[:5],
                "xpath_validated": validated,
                "required": orig_field.get("required", True),
                "data_type": orig_field.get("data_type", "text"),
                "extraction_source": orig_field.get("extraction_source"),
                "fixed_value": orig_field.get("fixed_value"),
            })

        return {"fields": merged_fields}

    def _merge_subtask_configs(
        self, subtask_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """合并多个子任务的导航配置（取第一个有效配置）。"""
        for result in subtask_results:
            cc = result.get("collection_config", {})
            if cc and (cc.get("nav_steps") or cc.get("common_detail_xpath")):
                return cc
        return {}

    def _merge_subtask_failures(
        self, subtask_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """汇总所有子任务的校验失败记录。"""
        all_failures: list[dict[str, Any]] = []
        for result in subtask_results:
            failures = result.get("validation_failures", [])
            all_failures.extend(failures)
        return all_failures
