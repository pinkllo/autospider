"""经验沉淀器 — 将完成的采集任务转化为 Spider Skill。

核心流程：
1. 从任务结果中提取结构化硬数据（XPath、导航步骤等）—— 零成本，纯代码
2. 汇总多子任务的错误轨迹和提取结果 —— Map-Reduce 合并
3. 调取一次 LLM 生成软经验总结 —— 仅一次调用
4. 拼装为 YAML + Markdown 的 Skill 文件
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import config
from ..logger import get_logger
from .skill_store import SkillStore

logger = get_logger(__name__)


def _extract_domain(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _extract_url_pattern(url: str) -> str:
    """从 URL 提取路径模式（将具体 ID 替换为通配符）。"""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        # 将纯数字段替换为 *
        import re
        pattern = re.sub(r"/\d+", "/*", path)
        return pattern or "/"
    except Exception:
        return "/"


class SkillSedimenter:
    """经验沉淀器。

    将 Pipeline 执行产物转化为持久化的 Spider Skill 文件。
    """

    def __init__(self, skills_dir: str | Path | None = None):
        self.store = SkillStore(skills_dir=skills_dir)

    def sediment_from_pipeline_result(
        self,
        *,
        list_url: str,
        task_description: str,
        fields: list[dict[str, Any]],
        collection_config: dict[str, Any] | None = None,
        extraction_config: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        validation_failures: list[dict[str, Any]] | None = None,
        subtask_names: list[str] | None = None,
    ) -> Path | None:
        """从单个 Pipeline 运行结果沉淀 Skill。

        Args:
            list_url: 列表页 URL
            task_description: 任务描述
            fields: 原始字段定义列表（包含 name + description）
            collection_config: 探索阶段生成的导航配置
            extraction_config: 字段探索阶段生成的提取配置
            summary: Pipeline 执行摘要
            validation_failures: 校验失败记录
            subtask_names: 子任务名称列表（多子任务聚合场景）

        Returns:
            生成的 Skill 文件路径，如果沉淀失败则返回 None
        """
        try:
            summary = summary or {}
            collection_config = collection_config or {}
            extraction_config = extraction_config or {}
            validation_failures = validation_failures or []

            # 检查任务是否成功（至少有一些数据产出）
            success_count = int(summary.get("success_count", 0) or 0)
            total_urls = int(summary.get("total_urls", 0) or 0)
            if success_count <= 0:
                logger.debug("[SkillSedimenter] 任务无成功记录，跳过沉淀")
                return None

            domain = _extract_domain(list_url)
            if not domain:
                logger.debug("[SkillSedimenter] 无法从 URL 提取域名，跳过沉淀")
                return None

            # 第一步：提取结构化硬数据（纯代码，不用 LLM）
            skill_data = self._extract_structured_data(
                domain=domain,
                list_url=list_url,
                task_description=task_description,
                fields=fields,
                collection_config=collection_config,
                extraction_config=extraction_config,
                summary=summary,
                subtask_names=subtask_names,
            )

            # 第二步：生成软经验总结（调一次 LLM）
            insights = self._generate_insights(
                domain=domain,
                fields=fields,
                extraction_config=extraction_config,
                validation_failures=validation_failures,
                summary=summary,
            )

            # 第三步：保存
            return self.store.save(skill_data, insights)

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
    ) -> Path | None:
        """从多个子任务结果聚合沉淀为一个统一 Skill（Map-Reduce）。

        Args:
            list_url: 主任务列表页 URL
            task_description: 主任务描述
            fields: 原始字段定义列表
            subtask_results: 子任务结果列表，每个元素包含:
                - name: 子任务名称
                - collection_config: 导航配置
                - extraction_config: 提取配置
                - summary: 执行摘要
                - validation_failures: 校验失败记录
        """
        try:
            if not subtask_results:
                return None

            # Map: 从各子任务提取 XPath
            merged_xpaths = self._merge_subtask_xpaths(subtask_results, fields)
            merged_collection = self._merge_subtask_configs(subtask_results)
            merged_failures = self._merge_subtask_failures(subtask_results)
            subtask_names = [str(r.get("name", "")) for r in subtask_results if r.get("name")]

            # 合并摘要
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
                list_url=list_url,
                task_description=task_description,
                fields=fields,
                collection_config=merged_collection,
                extraction_config=merged_xpaths,
                summary=merged_summary,
                validation_failures=merged_failures,
                subtask_names=subtask_names,
            )

        except Exception as exc:
            logger.debug("[SkillSedimenter] 子任务聚合沉淀失败: %s", exc)
            return None

    # ===== 内部方法 =====

    def _extract_structured_data(
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
    ) -> dict[str, Any]:
        """提取结构化硬数据（纯代码逻辑，不用 LLM）。"""
        # 构建字段描述索引：field_name -> description
        field_desc_map = {
            str(f.get("name", "")): str(f.get("description", ""))
            for f in fields
            if isinstance(f, dict) and f.get("name")
        }

        # 字段经验
        fields_experience = []
        extraction_fields = extraction_config.get("fields", [])
        for ef in extraction_fields:
            if not isinstance(ef, dict):
                continue
            name = str(ef.get("name", ""))
            if not name:
                continue

            fields_experience.append({
                "field_name": name,
                "original_description": field_desc_map.get(name, ""),
                "primary_xpath": ef.get("xpath"),
                "fallback_xpaths": ef.get("xpath_fallbacks", []),
                "confidence": 0.9 if ef.get("xpath_validated") else 0.6,
                "validated": bool(ef.get("xpath_validated")),
                "data_type": ef.get("data_type", "text"),
                "extraction_source": ef.get("extraction_source"),
                "fixed_value": ef.get("fixed_value"),
            })

        # 导航步骤
        nav_steps = []
        for step in collection_config.get("nav_steps", []):
            if not isinstance(step, dict):
                continue
            nav_steps.append({
                "action": str(step.get("action", "")),
                "xpath": step.get("xpath") or step.get("target_xpath"),
                "value": step.get("value"),
                "description": str(step.get("description", "")),
            })

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)

        data: dict[str, Any] = {
            "domain": domain,
            "list_url": list_url,
            "url_pattern": _extract_url_pattern(list_url),
            "task_description": task_description,
            "status": "validated",
            "confidence": round(success_count / max(total_urls, 1), 2),
            "total_executions": 1,
            "total_urls_processed": total_urls,
            "success_rate": round(success_count / max(total_urls, 1), 2),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        if nav_steps:
            data["nav_steps"] = nav_steps
        if collection_config.get("common_detail_xpath"):
            data["detail_link_xpath"] = collection_config["common_detail_xpath"]
        if collection_config.get("pagination_xpath"):
            data["pagination_xpath"] = collection_config["pagination_xpath"]
        if collection_config.get("jump_widget_xpath"):
            data["jump_widget_xpath"] = collection_config["jump_widget_xpath"]

        if fields_experience:
            data["fields_experience"] = fields_experience

        if subtask_names:
            data["subtask_count"] = len(subtask_names)
            data["subtask_names"] = subtask_names

        return data

    def _generate_insights(
        self,
        *,
        domain: str,
        fields: list[dict[str, Any]],
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str:
        """生成 LLM 软经验总结。

        如果 LLM 不可用或调用失败，返回基于规则生成的基础总结。
        """
        # 先生成一份基于规则的基础总结
        rule_based = self._rule_based_insights(
            domain=domain,
            fields=fields,
            extraction_config=extraction_config,
            validation_failures=validation_failures,
            summary=summary,
        )

        # 尝试调用 LLM 生成更高质量的总结
        try:
            llm_insights = self._llm_insights(
                domain=domain,
                extraction_config=extraction_config,
                validation_failures=validation_failures,
                summary=summary,
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
        """基于规则生成基础总结（无需 LLM）。"""
        lines: list[str] = []
        lines.append(f"# {domain} 站点采集经验\n")

        # 成功率
        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        if total_urls > 0:
            rate = success_count / total_urls * 100
            lines.append(f"## 基础数据")
            lines.append(f"- 成功率: {rate:.0f}% ({success_count}/{total_urls})")

        # 字段提取情况
        ext_fields = extraction_config.get("fields", [])
        if ext_fields:
            lines.append(f"\n## 字段提取")
            for ef in ext_fields:
                if not isinstance(ef, dict):
                    continue
                name = str(ef.get("name", ""))
                xpath = ef.get("xpath")
                validated = ef.get("xpath_validated", False)
                status = "✓ 已验证" if validated else ("⚠ 未验证" if xpath else "✗ 无 XPath")
                lines.append(f"- **{name}**: {status}")

        # 失败记录
        if validation_failures:
            lines.append(f"\n## 已知问题")
            # 汇总失败原因
            failure_reasons: Counter[str] = Counter()
            for fail in validation_failures:
                for f in fail.get("fields", []):
                    if f.get("error"):
                        failure_reasons[str(f["error"])] += 1

            for reason, count in failure_reasons.most_common(5):
                lines.append(f"- {reason}（出现 {count} 次）")

        return "\n".join(lines)

    def _llm_insights(
        self,
        *,
        domain: str,
        extraction_config: dict[str, Any],
        validation_failures: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str | None:
        """调用 LLM 生成高质量的经验总结。仅一次调用。"""
        if not config.llm.api_key:
            return None

        # 构建浓缩上下文
        context_parts: list[str] = []
        context_parts.append(f"站点域名: {domain}")

        success_count = int(summary.get("success_count", 0) or 0)
        total_urls = int(summary.get("total_urls", 0) or 0)
        context_parts.append(f"成功率: {success_count}/{total_urls}")

        # 字段提取概况
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

        # 失败摘要（只取关键信息，限制长度）
        if validation_failures:
            fail_summary: list[str] = []
            for fail in validation_failures[:5]:  # 最多 5 条
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
            f"请基于以上信息，写出一份简短的站点采集经验报告（Markdown 格式），包含：\n"
            f"1. 一个标题：# {domain} 站点采集经验\n"
            f"2. 站点特征小结（2-3 句话）\n"
            f"3. 避坑指南（如有失败记录，针对性地给出建议；如无失败，写'暂无已知问题'）\n"
            f"4. 优化建议（并发度、延迟等策略性建议）\n\n"
            f"要求极其简洁，总共不超过 200 字。只输出 Markdown，不要多余解释。"
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

    def _merge_subtask_xpaths(
        self,
        subtask_results: list[dict[str, Any]],
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Map-Reduce: 合并多个子任务的 XPath（投票机制）。"""
        # 按字段名收集所有子任务的 XPath
        field_xpaths: dict[str, list[str]] = {}  # field_name -> [xpath1, xpath2, ...]
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

        # 投票选出每个字段的最高频 XPath
        merged_fields: list[dict[str, Any]] = []
        field_map = {str(f.get("name", "")): f for f in fields if isinstance(f, dict)}

        for name, xpaths in field_xpaths.items():
            counter = Counter(xpaths)
            top_xpath, top_count = counter.most_common(1)[0]

            # 其他 XPath 作为 fallback
            all_fallbacks = list(field_fallbacks.get(name, []))
            unique_fallbacks = []
            seen = {top_xpath}
            for fb in all_fallbacks:
                if fb not in seen:
                    seen.add(fb)
                    unique_fallbacks.append(fb)
            # 也把非最高频的 primary xpath 加入 fallback
            for xpath, _ in counter.most_common():
                if xpath not in seen:
                    seen.add(xpath)
                    unique_fallbacks.append(xpath)

            # 校验状态：多数通过才算通过
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
