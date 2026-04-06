from __future__ import annotations

import hashlib
import re

from ...domain.planning import ExecutionBrief, PlanNodeType, SubTask, SubTaskMode


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
                    parent_id=parent_id,
                    depth=depth + 1,
                    mode=mode,
                    execution_brief=execution_brief,
                )
            )
        return subtasks

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
        match = re.search(r"(\d+)\s*条", str(self.user_request or ""))
        if match:
            return f"{prefix}{match.group(1)}条"
        return ""

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
