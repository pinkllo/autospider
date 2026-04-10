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
import re
from typing import Any

from ..config import config
from ..logger import get_logger
from ..utils.string_maps import normalize_string_map
from .skill_store import (
    SkillDocument,
    SkillFieldRule,
    SkillRuleData,
    SkillStore,
    SkillVariantRule,
    extract_domain,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SkillPromotionContext:
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", normalize_string_map(self.context, drop_empty=False))


@dataclass(frozen=True, slots=True)
class SkillSedimentationPayload:
    list_url: str
    task_description: str
    fields: list[dict[str, Any]]
    promotion_context: SkillPromotionContext = field(default_factory=SkillPromotionContext)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    subtask_names: list[str] = field(default_factory=list)
    plan_knowledge: str = ""
    status: str = "validated"


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    domain: str
    list_url: str
    task_description: str
    status: str
    summary: dict[str, Any] = field(default_factory=dict)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    plan_knowledge: str = ""
    subtask_names: list[str] = field(default_factory=list)
    source: str = "single_run"
    page_state_signature: str = ""
    anchor_url: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillPromotionPayload:
    list_url: str
    task_description: str
    fields: list[dict[str, Any]]
    candidates: list[SkillCandidate] = field(default_factory=list)
    plan_knowledge: str = ""
    overwrite_existing: bool = False


class SkillSedimenter:
    """经验沉淀器。

    将 Pipeline 执行产物转化为结构化 SkillDocument，并交给 SkillStore 保存。
    """

    def __init__(self, skills_dir: str | Path | None = None):
        self.store = SkillStore(skills_dir=skills_dir)

    def build_candidate_from_payload(
        self,
        payload: SkillSedimentationPayload,
        *,
        source: str = "single_run",
    ) -> SkillCandidate | None:
        summary = dict(payload.summary or {})
        if int(summary.get("success_count", 0) or 0) <= 0:
            return None

        domain = extract_domain(payload.list_url)
        if not domain:
            return None

        collection_config = dict(payload.collection_config or {})
        promotion_context = payload.promotion_context
        extraction_evidence = list(payload.extraction_evidence or [])
        effective_extraction_config = self._build_effective_extraction_config(
            fields=payload.fields,
            extraction_config=dict(payload.extraction_config or {}),
            extraction_evidence=extraction_evidence,
            validation_failures=list(payload.validation_failures or []),
        )
        if not self._candidate_has_usable_rules(effective_extraction_config):
            return None
        return SkillCandidate(
            domain=domain,
            list_url=payload.list_url,
            task_description=payload.task_description,
            status=str(payload.status or "draft"),
            summary=summary,
            collection_config=collection_config,
            extraction_config=effective_extraction_config,
            extraction_evidence=extraction_evidence,
            validation_failures=list(payload.validation_failures or []),
            plan_knowledge=str(payload.plan_knowledge or ""),
            subtask_names=list(payload.subtask_names or []),
            source=source,
            page_state_signature=str(
                promotion_context.page_state_signature
                or collection_config.get("page_state_signature")
                or ""
            ),
            anchor_url=str(
                promotion_context.anchor_url or collection_config.get("anchor_url") or ""
            ),
            variant_label=str(
                promotion_context.variant_label or collection_config.get("variant_label") or ""
            ),
            context=normalize_string_map(promotion_context.context),
        )

    def promote_candidates(self, payload: SkillPromotionPayload) -> Path | None:
        try:
            candidates = [candidate for candidate in list(payload.candidates or []) if candidate.domain]
            if not candidates:
                return None

            domain = candidates[0].domain
            document = self._compile_document(
                domain=domain,
                list_url=payload.list_url,
                task_description=payload.task_description,
                fields=payload.fields,
                candidates=candidates,
                plan_knowledge=payload.plan_knowledge,
            )
            return self.store.save_document(
                domain,
                document,
                overwrite_existing=payload.overwrite_existing,
            )
        except Exception as exc:
            logger.debug("[SkillSedimenter] Candidate promotion failed: %s", exc)
            return None

    def sediment_from_pipeline_result(
        self,
        payload: SkillSedimentationPayload,
        *,
        overwrite_existing: bool = False,
    ) -> Path | None:
        """从单个 Pipeline 运行结果沉淀 Skill。

        Returns:
            生成的 SKILL.md 文件路径，如果沉淀失败则返回 None
        """
        try:
            candidate = self.build_candidate_from_payload(payload)
            if candidate is None:
                logger.debug("[SkillSedimenter] 任务无有效 candidate，跳过沉淀")
                return None
            return self.promote_candidates(
                SkillPromotionPayload(
                    list_url=payload.list_url,
                    task_description=payload.task_description,
                    fields=payload.fields,
                    candidates=[candidate],
                    plan_knowledge=payload.plan_knowledge,
                    overwrite_existing=overwrite_existing,
                )
            )
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
        overwrite_existing: bool = False,
        source: str = "subtask_run",
    ) -> Path | None:
        """从多个子任务结果聚合沉淀为一个统一 Skill（Map-Reduce）。"""
        try:
            if not subtask_results:
                return None

            candidates: list[SkillCandidate] = []
            for result in subtask_results:
                payload = SkillSedimentationPayload(
                    list_url=str(result.get("list_url") or list_url or ""),
                    task_description=str(result.get("task_description") or task_description or ""),
                    fields=fields,
                    promotion_context=SkillPromotionContext(
                        anchor_url=str(result.get("anchor_url") or ""),
                        page_state_signature=str(result.get("page_state_signature") or ""),
                        variant_label=str(result.get("variant_label") or ""),
                        context=normalize_string_map(result.get("context")),
                    ),
                    collection_config=dict(result.get("collection_config") or {}),
                    extraction_config=dict(result.get("extraction_config") or {}),
                    extraction_evidence=list(result.get("extraction_evidence") or []),
                    summary=dict(result.get("summary") or {}),
                    validation_failures=list(result.get("validation_failures") or []),
                    subtask_names=[str(result.get("name") or "")] if result.get("name") else [],
                    plan_knowledge=str(plan_knowledge or ""),
                    status="validated",
                )
                candidate = self.build_candidate_from_payload(
                    payload,
                    source=source,
                )
                if candidate is not None:
                    candidates.append(candidate)

            if not candidates:
                logger.debug("[SkillSedimenter] 所有子任务均无有效 candidate，跳过沉淀")
                return None

            return self.promote_candidates(
                SkillPromotionPayload(
                    list_url=list_url,
                    task_description=task_description,
                    fields=fields,
                    candidates=candidates,
                    plan_knowledge=plan_knowledge,
                    overwrite_existing=overwrite_existing,
                )
            )
        except Exception as exc:
            logger.debug("[SkillSedimenter] 子任务聚合沉淀失败: %s", exc)
            return None

    def _build_variant_rule(
        self,
        *,
        candidate: SkillCandidate,
        fields: list[dict[str, Any]],
    ) -> SkillVariantRule:
        field_desc_map = {
            str(f.get("name", "")): str(f.get("description", ""))
            for f in fields
            if isinstance(f, dict) and f.get("name")
        }
        field_rules = self._build_field_rules(candidate.extraction_config, field_desc_map)
        collection_config = dict(candidate.collection_config or {})
        nav_steps = self._build_nav_steps(collection_config)
        jump_input_selector, jump_button_selector = self._extract_jump_selectors(collection_config)
        label = str(candidate.variant_label or "").strip()
        if not label:
            label = str((candidate.context or {}).get("category_name") or "").strip()
        if not label:
            label = str(candidate.task_description or "").strip()

        return SkillVariantRule(
            label=label,
            page_state_signature=str(candidate.page_state_signature or ""),
            anchor_url=str(candidate.anchor_url or ""),
            task_description=str(candidate.task_description or ""),
            context=normalize_string_map(candidate.context),
            success_rate=float(candidate.summary.get("success_rate", 0.0) or 0.0),
            success_rate_text=self._build_success_rate_text(candidate.summary),
            detail_xpath=str(collection_config.get("common_detail_xpath") or ""),
            pagination_xpath=str(collection_config.get("pagination_xpath") or ""),
            jump_input_selector=jump_input_selector,
            jump_button_selector=jump_button_selector,
            nav_steps=nav_steps,
            fields=field_rules,
        )

    def _compile_document(
        self,
        *,
        domain: str,
        list_url: str,
        task_description: str,
        fields: list[dict[str, Any]],
        candidates: list[SkillCandidate],
        plan_knowledge: str = "",
    ) -> SkillDocument:
        ordered_candidates = sorted(
            candidates,
            key=lambda candidate: (
                str(candidate.page_state_signature or ""),
                str(candidate.variant_label or ""),
                str(candidate.task_description or ""),
            ),
        )
        primary = ordered_candidates[0]
        primary_collection = dict(primary.collection_config or {})
        summary = self._merge_candidate_summaries(ordered_candidates)
        merged_extraction_config = self._merge_candidate_xpaths(ordered_candidates, fields)
        rules = self._build_rule_data(
            domain=domain,
            list_url=list_url,
            task_description=task_description,
            fields=fields,
            collection_config=primary_collection,
            extraction_config=merged_extraction_config,
            summary=summary,
            subtask_names=self._merge_candidate_subtask_names(ordered_candidates),
            status=str(primary.status or "validated"),
            variant_count=len(ordered_candidates),
        )
        variants = [
            self._build_variant_rule(candidate=candidate, fields=fields)
            for candidate in ordered_candidates
        ]
        rules = SkillRuleData(
            **{**rules.__dict__, "variants": variants}
        )
        insights = self._generate_insights(
            domain=domain,
            fields=fields,
            extraction_config=merged_extraction_config,
            validation_failures=self._merge_candidate_failures(ordered_candidates),
            summary=summary,
            plan_knowledge=plan_knowledge,
        )
        return self._build_skill_document(rules=rules, insights=insights)

    def _build_field_rules(
        self,
        extraction_config: dict[str, Any],
        field_desc_map: dict[str, str],
    ) -> dict[str, SkillFieldRule]:
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
                replace_primary=bool(ef.get("replace_primary")),
            )
        return field_rules

    def _build_nav_steps(self, collection_config: dict[str, Any]) -> list[dict[str, str]]:
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
        return nav_steps

    def _extract_jump_selectors(self, collection_config: dict[str, Any]) -> tuple[str, str]:
        jump_widget = collection_config.get("jump_widget_xpath")
        jump_input_selector = ""
        jump_button_selector = ""
        if isinstance(jump_widget, dict):
            jump_input_selector = str(jump_widget.get("input") or "")
            jump_button_selector = str(jump_widget.get("button") or "")
        return jump_input_selector, jump_button_selector

    def _build_success_rate_text(self, summary: dict[str, Any]) -> str:
        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        if total_urls <= 0:
            return ""
        success_rate = round(success_count / max(total_urls, 1), 2)
        return f"{success_rate * 100:.0f}% ({success_count}/{total_urls})"

    def _merge_candidate_xpaths(
        self,
        candidates: list[SkillCandidate],
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        subtask_results = [
            {"extraction_config": dict(candidate.extraction_config or {})}
            for candidate in candidates
        ]
        return self._merge_subtask_xpaths(subtask_results, fields)

    def _merge_candidate_failures(self, candidates: list[SkillCandidate]) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for candidate in candidates:
            failures.extend(list(candidate.validation_failures or []))
        return failures

    def _candidate_has_usable_rules(self, extraction_config: dict[str, Any]) -> bool:
        for field in list(dict(extraction_config or {}).get("fields") or []):
            if not isinstance(field, dict):
                continue
            if str(field.get("xpath") or "").strip():
                return True
            source = str(field.get("extraction_source") or "").strip().lower()
            fixed_value = str(field.get("fixed_value") or "").strip()
            if source in {"constant", "subtask_context", "task_url"} and fixed_value:
                return True
        return False

    def _build_effective_extraction_config(
        self,
        *,
        fields: list[dict[str, Any]],
        extraction_config: dict[str, Any],
        extraction_evidence: list[dict[str, Any]],
        validation_failures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        successful_records = [
            {"extraction_config": dict(item.get("extraction_config") or {})}
            for item in extraction_evidence
            if isinstance(item, dict) and item.get("success")
        ]
        if successful_records:
            merged = self._merge_subtask_xpaths(
                successful_records,
                fields,
                base_fields=list(dict(extraction_config or {}).get("fields") or []),
                validation_failures=list(validation_failures or []),
            )
            if self._candidate_has_usable_rules(merged):
                return self._merge_evidence_into_config(
                    base_config=extraction_config,
                    merged_fields=merged,
                )
        return dict(extraction_config or {})

    def _merge_evidence_into_config(
        self,
        *,
        base_config: dict[str, Any],
        merged_fields: dict[str, Any],
    ) -> dict[str, Any]:
        merged_config = dict(base_config or {})
        merged_config["fields"] = list(dict(merged_fields or {}).get("fields") or [])
        return merged_config

    def _merge_candidate_subtask_names(self, candidates: list[SkillCandidate]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            for name in list(candidate.subtask_names or []):
                text = str(name or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    names.append(text)
        return names

    def _merge_candidate_summaries(self, candidates: list[SkillCandidate]) -> dict[str, Any]:
        total_success = 0
        total_urls = 0
        for candidate in candidates:
            total_success += int(candidate.summary.get("success_count", 0) or 0)
            total_urls += int(candidate.summary.get("total_urls", 0) or 0)
        return {
            "success_count": total_success,
            "total_urls": total_urls,
        }

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
        variant_count: int = 0,
    ) -> SkillRuleData:
        """提取结构化规则层（纯代码逻辑，不用 LLM）。"""
        field_desc_map = {
            str(f.get("name", "")): str(f.get("description", ""))
            for f in fields
            if isinstance(f, dict) and f.get("name")
        }
        field_rules = self._build_field_rules(extraction_config, field_desc_map)
        nav_steps = self._build_nav_steps(collection_config)

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        success_rate = round(success_count / max(total_urls, 1), 2)
        success_rate_text = self._build_success_rate_text(summary)
        jump_input_selector, jump_button_selector = self._extract_jump_selectors(collection_config)

        return SkillRuleData(
            domain=domain,
            name=f"{domain} 站点采集",
            description=self._build_skill_description(
                domain=domain,
                collection_config=collection_config,
                extraction_config=extraction_config,
                variant_count=variant_count,
                status=status,
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

    def _build_skill_description(
        self,
        *,
        domain: str,
        collection_config: dict[str, Any],
        extraction_config: dict[str, Any],
        variant_count: int,
        status: str,
    ) -> str:
        tags: list[str] = []
        if variant_count > 1:
            tags.append(f"覆盖 {variant_count} 个分类变体")
        if collection_config.get("nav_steps"):
            tags.append("含页面导航规则")
        if collection_config.get("pagination_xpath") or collection_config.get("jump_widget_xpath"):
            tags.append("含分页处理")
        validated_fields = sum(
            1
            for field in list(extraction_config.get("fields") or [])
            if isinstance(field, dict) and field.get("xpath_validated")
        )
        if validated_fields > 0:
            tags.append(f"{validated_fields} 个字段已验证")
        if not tags:
            tags.append("聚焦列表页采集经验")
        state = "已验证" if status == "validated" else "草稿"
        return f"{domain} 数据采集技能，{'，'.join(tags)}。状态: {state}。"

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

    def _build_insight_context(
        self,
        *,
        domain: str,
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
        plan_knowledge: str = "",
    ) -> str:
        context_parts: list[str] = [f"站点域名: {domain}"]

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        context_parts.append(f"成功率: {success_count}/{total_urls}")

        if plan_knowledge:
            context_parts.append(f"规划发现过程记录：\n{plan_knowledge[:3000]}")

        field_summary = self._summarize_field_patterns(extraction_config)
        if field_summary:
            context_parts.append(field_summary)

        variant_summary = self._summarize_variant_patterns(extraction_config)
        if variant_summary:
            context_parts.append(variant_summary)

        failure_summary = self._summarize_failure_patterns(validation_failures)
        if failure_summary:
            context_parts.append(failure_summary)

        return "\n\n".join(context_parts)

    def _summarize_field_patterns(self, extraction_config: dict[str, Any]) -> str:
        ext_fields = [
            field for field in list(extraction_config.get("fields") or []) if isinstance(field, dict)
        ]
        if not ext_fields:
            return ""

        field_lines: list[str] = []
        validated_count = 0
        fallback_heavy_fields: list[str] = []
        for ef in ext_fields:
            name = str(ef.get("name") or "").strip()
            if not name:
                continue
            xpath = str(ef.get("xpath") or "").strip()
            validated = bool(ef.get("xpath_validated"))
            if validated:
                validated_count += 1
            fallbacks = [
                str(item).strip() for item in list(ef.get("xpath_fallbacks") or []) if str(item).strip()
            ]
            extraction_source = str(ef.get("extraction_source") or "").strip()
            if len(fallbacks) >= 2:
                fallback_heavy_fields.append(name)
            field_lines.append(
                f"- {name}: source={extraction_source or 'xpath'}, xpath={xpath or '无'}, "
                f"validated={validated}, fallback_count={len(fallbacks)}"
            )

        summary_lines = [
            f"字段规则概览: 共 {len(field_lines)} 个字段，{validated_count} 个已验证。",
            *field_lines,
        ]
        if fallback_heavy_fields:
            summary_lines.append(
                f"字段稳定性提示: {', '.join(fallback_heavy_fields)} 存在较多 fallback，说明结构可能不稳定。"
            )
        return "\n".join(summary_lines)

    def _summarize_variant_patterns(self, extraction_config: dict[str, Any]) -> str:
        variants = [
            variant for variant in list(extraction_config.get("variants") or []) if isinstance(variant, dict)
        ]
        if not variants:
            return ""

        labels = [str(variant.get("label") or "").strip() for variant in variants]
        labels = [label for label in labels if label]
        sample_labels = ", ".join(labels[:6]) if labels else "未命名"
        return f"变体概览: 共 {len(variants)} 个变体，示例标签: {sample_labels}。"

    def _summarize_failure_patterns(self, validation_failures: list[dict[str, Any]]) -> str:
        if not validation_failures:
            return ""

        reason_counter: Counter[str] = Counter()
        field_counter: Counter[str] = Counter()
        for fail in validation_failures:
            for field in list(fail.get("fields") or []):
                if not isinstance(field, dict):
                    continue
                reason = self._normalize_failure_reason(field.get("error"))
                if reason:
                    reason_counter[reason] += 1
                name = str(field.get("field_name") or "").strip()
                if name:
                    field_counter[name] += 1

        if not reason_counter and not field_counter:
            return ""

        lines = ["失败模式概览:"]
        for reason, count in reason_counter.most_common(5):
            lines.append(f"- 根因: {reason}（{count} 次）")
        if field_counter:
            fields = ", ".join(f"{name}({count})" for name, count in field_counter.most_common(5))
            lines.append(f"- 高频失败字段: {fields}")
        return "\n".join(lines)

    def _normalize_failure_reason(self, error: Any) -> str:
        text = str(error or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        normalized_patterns = [
            (r"timeout|timed out|超时", "等待超时或页面未稳定"),
            (r"not found|no such element|未找到|不存在", "元素定位失败"),
            (r"empty|为空|blank", "提取结果为空"),
            (r"stale", "DOM 刷新导致元素失效"),
            (r"intercepted|click", "点击或交互失败"),
        ]
        for pattern, label in normalized_patterns:
            if re.search(pattern, lowered):
                return label
        return text[:80]

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
        ext_fields = [
            field for field in list(extraction_config.get("fields") or []) if isinstance(field, dict)
        ]

        overview: list[str] = []
        if total_urls > 0:
            rate = success_count / total_urls * 100
            overview.append(f"本次沉淀成功率 {rate:.0f}% ({success_count}/{total_urls})")
        validated_count = sum(1 for field in ext_fields if field.get("xpath_validated"))
        if ext_fields:
            overview.append(f"{validated_count}/{len(ext_fields)} 个字段规则已验证")
        if overview:
            parts.append("- 总览：" + "；".join(overview) + "。")

        reusable_rules: list[str] = []
        fallback_heavy_fields: list[str] = []
        unvalidated_fields: list[str] = []
        for field in ext_fields:
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            fallbacks = [
                str(item).strip() for item in list(field.get("xpath_fallbacks") or []) if str(item).strip()
            ]
            if len(fallbacks) >= 2:
                fallback_heavy_fields.append(name)
            if not field.get("xpath_validated"):
                unvalidated_fields.append(name)
        if validated_count == len(ext_fields) and ext_fields:
            reusable_rules.append("主字段规则整体较稳定，可优先复用当前提取路径")
        if fallback_heavy_fields:
            reusable_rules.append(
                f"字段 {', '.join(fallback_heavy_fields)} 需要依赖多个 fallback，页面结构可能随状态变化"
            )
        if unvalidated_fields:
            reusable_rules.append(
                f"字段 {', '.join(unvalidated_fields)} 尚未稳定验证，不宜当作强规则沉淀"
            )
        if reusable_rules:
            parts.append("- 可复用经验：" + "；".join(reusable_rules) + "。")

        failure_summary = self._summarize_failure_patterns(validation_failures)
        if failure_summary:
            lines = [line.strip() for line in failure_summary.splitlines() if line.strip()]
            if len(lines) > 1:
                parts.append("- 风险提示：" + "；".join(lines[1:]) + "。")
        elif not parts:
            parts.append("- 暂无足够证据生成高价值经验，建议补充更多成功/失败样本后再沉淀。")

        return "\n".join(parts)

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

        context = self._build_insight_context(
            domain=domain,
            extraction_config=extraction_config,
            validation_failures=validation_failures,
            summary=summary,
            plan_knowledge=plan_knowledge,
        )

        prompt = (
            f"你是一名资深爬虫工程师，正在沉淀 {domain} 的站点技能。\n"
            f"以下是本次运行的关键证据：\n\n{context}\n\n"
            "请基于证据提炼真正值得未来复用的经验，而不是复述模板。\n"
            "输出要求：\n"
            "1. 只写高价值经验，宁缺毋滥，不要为了凑结构硬写。\n"
            "2. 优先总结跨页面/跨变体可复用的策略，其次再写少数特有差异。\n"
            "3. 明确指出哪些规则稳定、哪些规则脆弱、哪些现象只是样本级命中。\n"
            "4. 不要使用固定标题如“站点特征/避坑指南/优化建议”，改用 3-6 条 bullet。\n"
            "5. 每条 bullet 都要尽量回答‘为什么这条经验值得未来复用’。\n"
            "6. 不要编造未在证据中出现的信息。\n\n"
            "请直接输出 markdown bullet 列表，控制在 3-6 条，每条 1 句话。"
        )

        try:
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI

            from ..llm.streaming import invoke_with_stream

            llm = ChatOpenAI(
                api_key=config.llm.api_key,
                base_url=config.llm.api_base,
                model=config.llm.model,
                temperature=0.3,
                max_tokens=1024,
            )
            response = invoke_with_stream(llm, [HumanMessage(content=prompt)])
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
        *,
        base_fields: list[dict[str, Any]] | None = None,
        validation_failures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Map-Reduce: 保守合并多个子任务的 XPath。"""
        field_map = {str(f.get("name", "")): f for f in fields if isinstance(f, dict)}
        base_field_map = {
            str(f.get("name", "")): f
            for f in list(base_fields or [])
            if isinstance(f, dict) and str(f.get("name", "")).strip()
        }
        failure_field_names = self._extract_failure_field_names(validation_failures or [])

        candidates_by_field: dict[str, list[dict[str, Any]]] = {}
        fallbacks_by_field: dict[str, list[str]] = {}
        for result in subtask_results:
            ext_config = dict(result.get("extraction_config") or {})
            for ef in list(ext_config.get("fields") or []):
                if not isinstance(ef, dict):
                    continue
                name = str(ef.get("name") or "").strip()
                xpath = str(ef.get("xpath") or "").strip()
                if not name or not xpath:
                    continue
                candidates_by_field.setdefault(name, []).append(ef)
                for fb in list(ef.get("xpath_fallbacks") or []):
                    fb_text = str(fb or "").strip()
                    if fb_text:
                        fallbacks_by_field.setdefault(name, []).append(fb_text)

        merged_fields: list[dict[str, Any]] = []
        for name, candidate_fields in candidates_by_field.items():
            orig_field = field_map.get(name, {})
            base_field = base_field_map.get(name, {})
            base_xpath = str(base_field.get("xpath") or "").strip()
            base_validated = bool(base_field.get("xpath_validated"))

            validated_candidates = [
                field for field in candidate_fields if bool(field.get("xpath_validated")) and str(field.get("xpath") or "").strip()
            ]
            candidate_xpaths = [str(field.get("xpath") or "").strip() for field in candidate_fields if str(field.get("xpath") or "").strip()]
            validated_xpaths = [str(field.get("xpath") or "").strip() for field in validated_candidates]
            new_validated_xpath = next(
                (xpath for xpath in validated_xpaths if xpath and xpath != base_xpath),
                "",
            )

            replace_primary = False
            primary_xpath = base_xpath
            if not primary_xpath:
                primary_xpath = new_validated_xpath or (candidate_xpaths[0] if candidate_xpaths else "")
                replace_primary = bool(new_validated_xpath)
            elif self._should_replace_primary_xpath(
                field_name=name,
                base_xpath=base_xpath,
                candidate_xpaths=candidate_xpaths,
                validated_xpaths=validated_xpaths,
                failure_field_names=failure_field_names,
            ):
                primary_xpath = new_validated_xpath
                replace_primary = True

            if not primary_xpath:
                continue

            validated = base_validated if base_xpath and not replace_primary else False
            if primary_xpath in validated_xpaths:
                validated = True
            elif base_xpath and primary_xpath == base_xpath:
                validated = base_validated

            all_fallbacks = [
                *fallbacks_by_field.get(name, []),
                *[xpath for xpath in candidate_xpaths if xpath and xpath != primary_xpath],
            ]
            if base_xpath and base_xpath != primary_xpath:
                all_fallbacks.insert(0, base_xpath)
            all_fallbacks.extend(
                [
                    str(item).strip()
                    for item in list(base_field.get("xpath_fallbacks") or [])
                    if str(item).strip()
                ]
            )
            unique_fallbacks = []
            seen = {primary_xpath}
            for fallback in all_fallbacks:
                if fallback and fallback not in seen:
                    seen.add(fallback)
                    unique_fallbacks.append(fallback)

            merged_fields.append({
                "name": name,
                "description": orig_field.get("description", ""),
                "xpath": primary_xpath,
                "xpath_fallbacks": unique_fallbacks[:5],
                "xpath_validated": validated,
                "required": orig_field.get("required", True),
                "data_type": orig_field.get("data_type", "text"),
                "extraction_source": orig_field.get("extraction_source"),
                "fixed_value": orig_field.get("fixed_value"),
                "replace_primary": replace_primary,
            })

        return {"fields": merged_fields}

    def _extract_failure_field_names(self, validation_failures: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for failure in validation_failures:
            for field in list(failure.get("fields") or []):
                if not isinstance(field, dict):
                    continue
                name = str(field.get("field_name") or "").strip()
                if name:
                    names.add(name)
        return names

    def _should_replace_primary_xpath(
        self,
        *,
        field_name: str,
        base_xpath: str,
        candidate_xpaths: list[str],
        validated_xpaths: list[str],
        failure_field_names: set[str],
    ) -> bool:
        if not base_xpath:
            return False
        distinct_validated = [xpath for xpath in dict.fromkeys(validated_xpaths) if xpath and xpath != base_xpath]
        if not distinct_validated:
            return False
        if base_xpath in candidate_xpaths:
            return False
        if field_name in failure_field_names:
            return True
        return len(distinct_validated) >= 2 or len(validated_xpaths) >= 2

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
