"""Planning domain services — category semantics and subtask construction."""

from __future__ import annotations

import hashlib
import re

from autospider.common.utils.string_maps import normalize_string_map
from autospider.contexts.planning.domain.model import (
    ExecutionBrief,
    PlanNodeType,
    SubTask,
    SubTaskMode,
)

CATEGORY_PATH_KEY = "category_path"
CATEGORY_PATH_SEPARATOR = " > "
PLANNER_ACTION_HISTORY_LIMIT = 6


class PlannerCategorySemanticsMixin:
    def _build_subtask_context(
        self,
        name: str,
        parent_context: dict[str, str] | None = None,
    ) -> dict[str, str]:
        context = self._sanitize_context(parent_context)
        value = str(name or "").strip()
        if not value:
            return context
        category_path = self._extract_category_path(context)
        if not category_path or category_path[-1] != value:
            category_path.append(value)
        context["category_name"] = value
        context[CATEGORY_PATH_KEY] = CATEGORY_PATH_SEPARATOR.join(category_path)
        return context

    def _sanitize_context(self, context: dict[str, str] | None) -> dict[str, str]:
        return normalize_string_map(context)

    def _extract_category_path(self, context: dict[str, str] | None) -> list[str]:
        raw = str((context or {}).get(CATEGORY_PATH_KEY) or "").strip()
        if not raw:
            category_name = str((context or {}).get("category_name") or "").strip()
            return self._expand_category_segments(category_name)

        expanded_path: list[str] = []
        for item in raw.split(CATEGORY_PATH_SEPARATOR):
            expanded_path.extend(self._expand_category_segments(item))
        return [item.strip() for item in expanded_path if item.strip()]

    def _normalize_semantic_label(self, value: str) -> str:
        return "".join(str(value or "").split())

    def _format_context_path(self, context: dict[str, str] | None) -> str:
        category_path = self._extract_category_path(context)
        return CATEGORY_PATH_SEPARATOR.join(category_path) if category_path else "无"

    def _format_recent_actions(self, nav_steps: list[dict] | None) -> str:
        lines: list[str] = []
        for step in list(nav_steps or [])[-PLANNER_ACTION_HISTORY_LIMIT:]:
            action = str(step.get("action") or "").strip().lower()
            target = str(step.get("target_text") or step.get("clicked_element_text") or "").strip()
            if not action:
                continue
            if action == "click":
                lines.append(f"- 点击：{target or '未命名元素'}")
                continue
            if action == "type":
                text = str(step.get("text") or "").strip()
                lines.append(f"- 输入：{target or '输入框'} <- {text or '(空)'}")
                continue
            if action == "scroll":
                delta = step.get("scroll_delta")
                lines.append(f"- 滚动：{delta}")
                continue
            lines.append(f"- {action}：{target or '未命名动作'}")
        return "\n".join(lines) if lines else "无"

    def _build_semantic_state_signature(
        self,
        current_url: str,
        context: dict[str, str] | None,
    ) -> str:
        normalized_url = str(current_url or "").strip()
        semantic_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(context)
        ]
        semantic_path = [item for item in semantic_path if item]
        if not semantic_path:
            return normalized_url
        return f"{normalized_url}::{CATEGORY_PATH_SEPARATOR.join(semantic_path)}"

    def _is_same_page_category_cycle(
        self,
        current_url: str,
        child_url: str,
        current_context: dict[str, str] | None,
        child_context: dict[str, str] | None,
    ) -> bool:
        if str(current_url or "").strip() != str(child_url or "").strip():
            return False
        current_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(current_context)
        ]
        child_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(child_context)
        ]
        current_path = [item for item in current_path if item]
        child_path = [item for item in child_path if item]
        if not current_path or len(child_path) <= len(current_path):
            return False
        child_label = child_path[-1]
        return bool(child_label and child_label in current_path)

    def _expand_category_segments(self, label: str) -> list[str]:
        text = str(label or "").strip()
        if not text:
            return []
        group, leaf = self._split_grouped_category_label(text)
        if group and leaf:
            return [group, leaf]
        return [text]

    def _split_grouped_category_label(self, label: str) -> tuple[str, str]:
        text = str(label or "").strip()
        if not text:
            return "", ""
        for separator in ("-", "—", "–", ":", "：", "/", "|"):
            if separator not in text:
                continue
            group, leaf = text.split(separator, 1)
            group = group.strip()
            leaf = leaf.strip()
            if group and leaf:
                return group, leaf
        return "", text

    def _strip_category_group_prefix(self, label: str) -> str:
        _, leaf = self._split_grouped_category_label(label)
        return leaf or str(label or "").strip()

    def _normalize_category_leaf_label(self, label: str) -> str:
        return self._normalize_semantic_label(self._strip_category_group_prefix(label))

    def _build_parent_category_signature(self, category_path: list[str]) -> str:
        parent_path: list[str] = []
        for item in list(category_path or [])[:-1]:
            normalized = self._normalize_semantic_label(item)
            if normalized:
                parent_path.append(normalized)
        return CATEGORY_PATH_SEPARATOR.join(parent_path)

    def _get_current_category_label(self, context: dict[str, str] | None) -> str:
        raw_path = str((context or {}).get(CATEGORY_PATH_KEY) or "").strip()
        if raw_path:
            raw_parts = [item.strip() for item in raw_path.split(CATEGORY_PATH_SEPARATOR) if item.strip()]
            if raw_parts:
                return raw_parts[-1]
        return str((context or {}).get("category_name") or "").strip()


class PlannerSubtaskBuilderMixin:
    def _resolve_plan_node_type_for_state(
        self,
        page_type: str,
        nav_steps: list[dict] | None,
    ) -> PlanNodeType:
        normalized = str(page_type or "").strip().lower()
        if normalized == "list_page":
            return PlanNodeType.STATEFUL_LIST if list(nav_steps or []) else PlanNodeType.LEAF
        if normalized == "category":
            return PlanNodeType.CATEGORY
        return PlanNodeType.CATEGORY

    def _build_variant_label(self, context: dict[str, str] | None) -> str | None:
        label = self._format_context_path(context)
        if not label or label == "无":
            return None
        return label

    def _build_subtasks_from_variants(
        self,
        variants: list,
        *,
        analysis: dict,
        depth: int,
        mode: SubTaskMode = SubTaskMode.COLLECT,
        parent_id: str | None = None,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> list[SubTask]:
        subtasks: list[SubTask] = []
        seen_signatures: set[str] = set()
        raw_subtasks = list(analysis.get("subtasks") or [])

        for idx, variant in enumerate(variants):
            page_state_signature = str(variant.page_state_signature or "").strip()
            if not page_state_signature or page_state_signature in seen_signatures:
                continue
            seen_signatures.add(page_state_signature)

            raw = raw_subtasks[idx] if idx < len(raw_subtasks) else {}
            name = str(raw.get("name") or variant.variant_label or f"分类_{idx + 1}").strip()
            sanitized_context = self._sanitize_context(variant.context)
            scope = self._build_subtask_scope(raw=raw, context=sanitized_context)
            task_desc = (
                str(raw.get("task_description") or "").strip()
                or self._build_task_description_for_mode(sanitized_context, mode)
            )
            execution_brief = self._build_execution_brief(
                context=sanitized_context,
                mode=mode,
                task_description=task_desc,
                parent_execution_brief=parent_execution_brief,
            )
            subtasks.append(
                SubTask(
                    id=self._build_subtask_id(
                        mode=mode,
                        page_state_signature=page_state_signature,
                        context=sanitized_context,
                        fallback_index=idx + 1,
                    ),
                    name=name,
                    list_url=variant.resolved_url,
                    anchor_url=variant.anchor_url,
                    page_state_signature=page_state_signature,
                    variant_label=variant.variant_label or self._build_variant_label(variant.context),
                    task_description=task_desc,
                    priority=idx,
                    max_pages=raw.get("estimated_pages"),
                    nav_steps=list(variant.nav_steps or []),
                    context=sanitized_context,
                    scope=scope,
                    fixed_fields=self._build_subtask_fixed_fields(scope),
                    per_subtask_target_count=self._resolve_grouped_target_count(),
                    parent_id=parent_id,
                    depth=depth + 1,
                    mode=mode,
                    execution_brief=execution_brief,
                )
            )
        return subtasks

    def _build_subtask_scope(
        self,
        *,
        raw: dict,
        context: dict[str, str] | None,
    ) -> dict[str, object]:
        category_path = self._extract_category_path(context)
        scope_key = str(raw.get("scope_key") or "").strip()
        scope_label = str(raw.get("scope_label") or "").strip()
        if not scope_key and category_path:
            normalized = [self._normalize_semantic_label(item) for item in category_path if item]
            normalized = [item for item in normalized if item]
            if normalized:
                scope_key = "category:" + " > ".join(normalized)
        if not scope_label and category_path:
            scope_label = " > ".join(category_path)

        scope: dict[str, object] = {}
        if scope_key:
            scope["key"] = scope_key
        if scope_label:
            scope["label"] = scope_label
        if category_path:
            scope["path"] = list(category_path)
        return scope

    def _build_subtask_fixed_fields(
        self,
        scope: dict[str, object] | None,
    ) -> dict[str, str]:
        category_value = self._resolve_scope_label(scope)
        if not category_value:
            return {}
        return {
            "category": category_value,
            "category_name": category_value,
            "分类": category_value,
            "所属分类": category_value,
        }

    def _resolve_scope_label(self, scope: dict[str, object] | None) -> str:
        scope_dict = dict(scope or {})
        label = str(scope_dict.get("label") or "").strip()
        if label:
            return label
        path = scope_dict.get("path")
        if isinstance(path, (list, tuple)):
            segments = [str(item or "").strip() for item in path if str(item or "").strip()]
            if segments:
                return " > ".join(segments)
        return ""

    def _build_subtask_id(
        self,
        *,
        mode: SubTaskMode,
        page_state_signature: str,
        context: dict[str, str] | None,
        fallback_index: int,
    ) -> str:
        base = (
            str(page_state_signature or "").strip()
            or self._format_context_path(context)
            or f"task_{fallback_index}"
        )
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
        prefix = "expand" if mode == SubTaskMode.EXPAND else "leaf"
        return f"{prefix}_{digest}"

    def _build_task_description_for_mode(
        self,
        context: dict[str, str] | None,
        mode: SubTaskMode,
    ) -> str:
        if mode == SubTaskMode.EXPAND:
            return self._build_expand_task_description(context)
        return self._build_collect_task_description(context)

    def _build_expand_task_description(self, context: dict[str, str] | None) -> str:
        scope = self._format_context_path(context)
        count_text = self._resolve_requested_count_text()
        suffix = f"{count_text}" if count_text else ""
        return f"爬取“{scope}”下各个相关分类的项目{suffix}。"

    def _build_collect_task_description(self, context: dict[str, str] | None) -> str:
        scope = self._format_context_path(context)
        count_text = self._resolve_requested_count_text(prefix='前')
        quantity = f"{count_text}" if count_text else "相关"
        return f"采集当前“{scope}”范围下{quantity}项目记录，提取项目名称与所属分类名称。"

    def _resolve_requested_count_text(self, prefix: str = "各") -> str:
        grouped_target_count = self._resolve_grouped_target_count()
        if grouped_target_count is not None:
            return f"{prefix}{grouped_target_count}条"
        match = re.search(r"(\d+)\s*条", str(self.user_request or ""))
        if match:
            return f"{prefix}{match.group(1)}条"
        return ""

    def _resolve_grouped_target_count(self) -> int | None:
        resolver = getattr(self, "_get_grouping_semantics", None)
        if not callable(resolver):
            return None
        grouping = dict(resolver() or {})
        if str(grouping.get("group_by") or "").strip().lower() != "category":
            return None
        value = grouping.get("per_group_target_count")
        try:
            count = int(value)
        except (TypeError, ValueError):
            return None
        return count if count > 0 else None

    def _build_execution_brief(
        self,
        *,
        context: dict[str, str] | None,
        mode: SubTaskMode,
        task_description: str,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> ExecutionBrief:
        category_path = self._extract_category_path(context)
        current_scope = category_path[-1] if category_path else str((context or {}).get("category_name") or "").strip()
        parent_chain = [item for item in category_path[:-1] if item]
        if parent_execution_brief and not parent_chain:
            parent_chain = list(parent_execution_brief.parent_chain or [])
        if mode == SubTaskMode.EXPAND:
            next_action = (
                f"先判断当前页面是否仍存在属于“{current_scope}”的下级相关分类入口；"
                "若存在则新增子任务，不直接进入详情链接采集。"
            )
            stop_rule = (
                "当页面未识别出更深相关分类，或剩余入口仅为兄弟切换、祖先回跳、筛选项或详情链接时，"
                "停止拆分并开始采集当前分类。"
            )
            do_not = [
                "不要把祖先分类或返回上一级入口当作新的子任务",
                "不要把同层兄弟分类切换误判为继续下钻",
                "不要在仍需继续拆分时直接采集当前列表",
            ]
        else:
            next_action = "直接在当前页面收集详情链接并翻页，不再继续拆分分类。"
            stop_rule = "当无新详情链接、达到目标数量，或无法继续翻页时结束当前采集任务。"
            do_not = [
                "不要再把兄弟分类切换或祖先回跳入口当作新的分类任务",
                "不要偏离当前分类作用域去采集其他分类的数据",
            ]
        return ExecutionBrief(
            parent_chain=parent_chain,
            current_scope=current_scope,
            objective=task_description,
            next_action=next_action,
            stop_rule=stop_rule,
            do_not=do_not,
        )

    def _build_collect_execution_brief(
        self,
        context: dict[str, str] | None,
        *,
        task_description: str,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> ExecutionBrief:
        return self._build_execution_brief(
            context=context,
            mode=SubTaskMode.COLLECT,
            task_description=task_description,
            parent_execution_brief=parent_execution_brief,
        )

    def _register_sibling_categories(self, subtasks: list[SubTask]) -> None:
        registry = self._get_sibling_category_registry()
        for subtask in subtasks:
            category_path = self._extract_category_path(subtask.context)
            parent_signature = self._build_parent_category_signature(category_path)
            leaf_label = self._normalize_category_leaf_label(category_path[-1] if category_path else "")
            if not parent_signature or not leaf_label:
                continue
            registry.setdefault(parent_signature, set()).add(leaf_label)

    def _get_sibling_category_registry(self) -> dict[str, set[str]]:
        registry = getattr(self, "_sibling_category_registry", None)
        if registry is None:
            registry = {}
            self._sibling_category_registry = registry
        return registry
