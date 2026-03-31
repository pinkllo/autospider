"""经验沉淀器 — 将完成的采集任务转化为标准 Agent Skills 格式。

核心流程：
1. 从任务结果中提取结构化硬数据（XPath、导航步骤等）—— 零成本，纯代码
2. 汇总多子任务的错误轨迹和提取结果 —— Map-Reduce 合并
3. 调取一次 LLM 生成软经验总结 —— 仅一次调用
4. 渲染为标准 SKILL.md（name + description frontmatter + 操作指南正文）
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
        import re
        pattern = re.sub(r"/\d+", "/*", path)
        return pattern or "/"
    except Exception:
        return "/"


class SkillSedimenter:
    """经验沉淀器。

    将 Pipeline 执行产物转化为标准 Agent Skills 格式的 SKILL.md 文件。
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
        plan_knowledge: str = "",
    ) -> Path | None:
        """从单个 Pipeline 运行结果沉淀 Skill。

        Returns:
            生成的 SKILL.md 文件路径，如果沉淀失败则返回 None
        """
        try:
            summary = summary or {}
            collection_config = collection_config or {}
            extraction_config = extraction_config or {}
            validation_failures = validation_failures or []

            success_count = int(summary.get("success_count", 0) or 0)
            if success_count <= 0:
                logger.debug("[SkillSedimenter] 任务无成功记录，跳过沉淀")
                return None

            domain = _extract_domain(list_url)
            if not domain:
                logger.debug("[SkillSedimenter] 无法从 URL 提取域名，跳过沉淀")
                return None

            # 第一步：提取结构化硬数据
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

            # 第二步：生成软经验总结
            insights = self._generate_insights(
                domain=domain,
                fields=fields,
                extraction_config=extraction_config,
                validation_failures=validation_failures,
                summary=summary,
                plan_knowledge=plan_knowledge,
            )

            # 第三步：渲染为标准 SKILL.md 并保存
            content = self._render_skill_md(skill_data, insights)
            return self.store.save(domain, content)

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
        field_desc_map = {
            str(f.get("name", "")): str(f.get("description", ""))
            for f in fields
            if isinstance(f, dict) and f.get("name")
        }

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

    def _render_skill_md(
        self,
        skill_data: dict[str, Any],
        insights: str,
    ) -> str:
        """将结构化数据和软经验渲染为标准 SKILL.md 内容。

        输出格式遵循 Agent Skills 标准：
        - YAML frontmatter: name + description
        - Markdown 正文: 结构化的站点采集操作指南
        """
        domain = skill_data["domain"]
        list_url = skill_data.get("list_url", "")
        task_description = skill_data.get("task_description", "")
        status = skill_data.get("status", "unknown")
        success_rate = skill_data.get("success_rate", 0)
        total_urls = skill_data.get("total_urls_processed", 0)
        success_count = round(total_urls * success_rate) if total_urls else 0

        # --- Frontmatter ---
        status_label = "已验证" if status == "validated" else "草稿"
        fm_name = f"{domain} 站点采集"
        fm_desc = (
            f"{domain} 数据采集技能。"
            f"包含列表页导航、分页处理和字段提取的操作指南。"
            f"状态: {status_label}。"
        )

        lines: list[str] = []
        lines.append("---")
        lines.append(f"name: {fm_name}")
        lines.append(f"description: {fm_desc}")
        lines.append("---")
        lines.append("")

        # --- 标题 ---
        lines.append(f"# {domain} 采集指南")
        lines.append("")

        # --- 基本信息 ---
        lines.append("## 基本信息")
        lines.append("")
        lines.append(f"- **列表页 URL**: `{list_url}`")
        lines.append(f"- **任务描述**: {task_description}")
        status_icon = "✅" if status == "validated" else "📝"
        lines.append(f"- **状态**: {status_icon} {status}")
        if total_urls > 0:
            lines.append(
                f"- **成功率**: {success_rate * 100:.0f}% ({success_count}/{total_urls})"
            )
        lines.append("")

        # --- 列表页导航 ---
        detail_xpath = skill_data.get("detail_link_xpath")
        pagination_xpath = skill_data.get("pagination_xpath")
        jump_widget = skill_data.get("jump_widget_xpath")
        nav_steps = skill_data.get("nav_steps", [])

        has_nav = detail_xpath or pagination_xpath or jump_widget or nav_steps
        if has_nav:
            lines.append("## 列表页导航")
            lines.append("")

            if detail_xpath:
                lines.append("### 详情链接定位")
                lines.append("")
                lines.append("使用以下 XPath 从列表页中定位每个详情条目的入口：")
                lines.append("")
                lines.append("```xpath")
                lines.append(detail_xpath)
                lines.append("```")
                lines.append("")

            if isinstance(jump_widget, dict) and jump_widget:
                lines.append("### 分页处理（跳转式）")
                lines.append("")
                lines.append("本站使用跳转式分页控件，操作步骤：")
                lines.append("")
                if jump_widget.get("input"):
                    lines.append(
                        f"1. 在页码输入框中输入目标页码，选择器: `{jump_widget['input']}`"
                    )
                if jump_widget.get("button"):
                    lines.append(
                        f"2. 点击跳转按钮，选择器: `{jump_widget['button']}`"
                    )
                lines.append("")
            elif pagination_xpath:
                lines.append("### 分页处理")
                lines.append("")
                lines.append(f"分页控件 XPath: `{pagination_xpath}`")
                lines.append("")

            if nav_steps:
                lines.append("### 导航步骤")
                lines.append("")
                for i, step in enumerate(nav_steps, 1):
                    action = step.get("action", "")
                    xpath = step.get("xpath", "")
                    value = step.get("value", "")
                    desc = step.get("description", "")
                    step_line = f"{i}. **{action}**"
                    if desc:
                        step_line += f" — {desc}"
                    lines.append(step_line)
                    if xpath:
                        lines.append(f"   - XPath: `{xpath}`")
                    if value:
                        lines.append(f"   - 值: `{value}`")
                lines.append("")

        # --- 字段提取规则 ---
        fields_exp = skill_data.get("fields_experience", [])
        if fields_exp:
            lines.append("## 字段提取规则")
            lines.append("")

            for fe in fields_exp:
                name = fe.get("field_name", "")
                desc = fe.get("original_description", "")
                data_type = fe.get("data_type", "text")
                primary_xpath = fe.get("primary_xpath", "")
                fallbacks = fe.get("fallback_xpaths", [])
                validated = fe.get("validated", False)
                confidence = fe.get("confidence", 0)
                extraction_source = fe.get("extraction_source")
                fixed_value = fe.get("fixed_value")

                heading = f"### {name}"
                if desc:
                    heading += f"（{desc}）"
                lines.append(heading)
                lines.append("")
                lines.append(f"- **数据类型**: {data_type}")

                if extraction_source in ("constant", "subtask_context"):
                    lines.append(f"- **提取方式**: {extraction_source}")
                    if fixed_value:
                        lines.append(f"- **固定值**: `{fixed_value}`")
                elif primary_xpath:
                    lines.append(f"- **主 XPath**: `{primary_xpath}`")
                    for fb in fallbacks:
                        lines.append(f"- **备选 XPath**: `{fb}`")

                status_mark = "✓ 已验证" if validated else "⚠ 未验证"
                lines.append(f"- **验证状态**: {status_mark}")
                lines.append(f"- **置信度**: {confidence}")
                lines.append("")

        # --- 子任务 ---
        subtask_names = skill_data.get("subtask_names", [])
        if subtask_names:
            lines.append("## 子任务")
            lines.append("")
            lines.append(f"本站共 {len(subtask_names)} 个子任务分类：")
            lines.append("")
            for sn in subtask_names:
                lines.append(f"- {sn}")
            lines.append("")

        # --- 站点经验 ---
        if insights:
            lines.append("## 站点特征与经验")
            lines.append("")
            lines.append(insights.strip())
            lines.append("")

        return "\n".join(lines)

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
            context_parts.append(f"DFS 发现过程记录：\n{plan_knowledge[:2000]}")

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
