"""Post-process planner analysis results into normalized subtask candidates."""

from __future__ import annotations

from autospider.contexts.planning.domain.model import PlannerCategoryCandidate


class PlannerAnalysisPostProcessMixin:
    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict:
        current_context = self._sanitize_context(node_context)
        normalized = dict(result or {})
        normalized = self._prune_backtrack_subtasks(
            normalized,
            current_context,
        )
        normalized = self._collapse_sibling_switches_to_leaf(
            normalized,
            current_context,
        )
        if not self._should_split_by_category():
            return normalized
        if self._extract_category_path(current_context):
            return normalized
        if not self._page_facts_support_grouped_split(normalized):
            return normalized

        fact_subtasks = self._build_page_fact_subtasks(normalized)
        if not fact_subtasks:
            self._set_analysis_candidates(normalized, [])
            return self._append_observation_note(
                normalized,
                "结构化分类分组已启用，但页面事实未提供可用的 category_candidates；未采用 subtasks 作为兜底来源。",
            )

        normalized["page_type"] = "category"
        normalized["subtasks"] = fact_subtasks
        note = "检测到结构化分类分组语义，按页面事实中的分类候选生成子任务。"
        return self._append_observation_note(normalized, note)

    def _prune_backtrack_subtasks(
        self,
        result: dict,
        context: dict[str, str] | None,
    ) -> dict:
        normalized = dict(result or {})
        subtasks = self._get_analysis_candidates(normalized)
        current_path = self._extract_category_path(context)
        if not subtasks or not current_path:
            return normalized

        current_path_norm = [self._normalize_semantic_label(item) for item in current_path if item]
        current_path_norm = [item for item in current_path_norm if item]
        if not current_path_norm:
            return normalized

        filtered_subtasks: list[dict] = []
        removed_names: list[str] = []
        for item in subtasks:
            name = str(item.get("name") or item.get("link_text") or "").strip()
            candidate_path = self._expand_category_segments(name)
            candidate_path_norm = [
                self._normalize_semantic_label(segment)
                for segment in candidate_path
                if segment
            ]
            candidate_path_norm = [segment for segment in candidate_path_norm if segment]
            if not candidate_path_norm:
                filtered_subtasks.append(item)
                continue
            if self._is_backtrack_candidate(current_path_norm, candidate_path_norm):
                removed_names.append(name or "/".join(candidate_path))
                continue
            filtered_subtasks.append(item)

        if not removed_names:
            return normalized

        self._set_analysis_candidates(normalized, filtered_subtasks)
        if filtered_subtasks:
            note = f"已过滤祖先/当前分类回跳入口: {'; '.join(removed_names)}"
            return self._append_observation_note(normalized, note)

        normalized["page_type"] = "list_page"
        note = f"候选分类仅包含祖先或当前分类回跳入口，停止继续拆分: {'; '.join(removed_names)}"
        self._set_analysis_candidates(normalized, [])
        if not str(normalized.get("task_description") or "").strip():
            normalized["task_description"] = self._build_collect_task_description(context)
        return self._append_observation_note(normalized, note)

    def _collapse_sibling_switches_to_leaf(
        self,
        result: dict,
        context: dict[str, str] | None,
    ) -> dict:
        normalized = dict(result or {})
        page_type = str(normalized.get("page_type") or "").strip().lower()
        if page_type != "category":
            return normalized

        current_label = self._get_current_category_label(context)
        subtask_names = self._extract_subtask_names(normalized)
        if not current_label or not subtask_names:
            return normalized
        looks_like_grouped_switch = self._looks_like_sibling_switch_group(current_label, subtask_names)
        looks_like_registered_switch = self._matches_registered_sibling_switches(context, subtask_names)
        if not looks_like_grouped_switch and not looks_like_registered_switch:
            return normalized

        display_label = self._strip_category_group_prefix(current_label)
        normalized["page_type"] = "list_page"
        self._set_analysis_candidates(normalized, [])
        normalized["task_description"] = self._build_collect_task_description(
            self._build_subtask_context(display_label, context)
        )
        note = (
            "检测到当前页面已进入具体分类，页面中剩余候选项属于同层兄弟分类切换，"
            "不再继续向下拆分。"
        )
        return self._append_observation_note(normalized, note)

    def _should_split_by_category(self) -> bool:
        resolver = getattr(self, "_get_grouping_semantics", None)
        if not callable(resolver):
            return False
        grouping = dict(resolver() or {})
        return str(grouping.get("group_by") or "").strip().lower() == "category"

    def _build_page_fact_subtasks(self, analysis: dict) -> list[dict]:
        resolver = getattr(self, "_get_grouping_semantics", None)
        grouping = dict(resolver() or {}) if callable(resolver) else {}
        requested = self._get_requested_category_filters(grouping)
        subtasks: list[dict] = []
        seen_scope_keys: set[str] = set()

        for raw in self._get_page_fact_candidates(analysis):
            candidate = PlannerCategoryCandidate.model_validate(raw)
            label = str(candidate.name or candidate.link_text).strip()
            if not label:
                continue
            if requested and not self._matches_requested_categories(label, requested):
                continue

            scope_key, scope_label = self._build_candidate_scope(label, candidate)
            if scope_key in seen_scope_keys:
                continue
            seen_scope_keys.add(scope_key)
            task_description = (
                str(candidate.task_description or "").strip()
                or self._build_category_candidate_task_description(label)
            )
            subtasks.append(
                {
                    "name": label,
                    "mark_id": candidate.mark_id,
                    "link_text": candidate.link_text or label,
                    "estimated_pages": candidate.estimated_pages,
                    "task_description": task_description,
                    "scope_key": scope_key,
                    "scope_label": scope_label,
                }
            )
        return subtasks

    def _get_requested_category_filters(self, grouping: dict) -> list[str]:
        mode = str(grouping.get("category_discovery_mode") or "").strip().lower()
        if mode != "manual":
            return []
        return [str(item or "").strip() for item in list(grouping.get("requested_categories") or []) if str(item or "").strip()]

    def _matches_requested_categories(self, label: str, requested_categories: list[str]) -> bool:
        candidate_tokens = {
            self._normalize_semantic_label(label),
            self._normalize_category_leaf_label(label),
            *[
                self._normalize_semantic_label(item)
                for item in self._expand_category_segments(label)
            ],
        }
        candidate_tokens = {item for item in candidate_tokens if item}
        for requested in requested_categories:
            requested_tokens = {
                self._normalize_semantic_label(requested),
                self._normalize_category_leaf_label(requested),
                *[
                    self._normalize_semantic_label(item)
                    for item in self._expand_category_segments(requested)
                ],
            }
            if candidate_tokens.intersection({item for item in requested_tokens if item}):
                return True
        return False

    def _build_candidate_scope(
        self,
        label: str,
        candidate: PlannerCategoryCandidate,
    ) -> tuple[str, str]:
        scope_context = self._build_subtask_context(label)
        scope_path = self._extract_category_path(scope_context)
        scope_key = str(candidate.scope_key or "").strip()
        if not scope_key:
            normalized = [self._normalize_semantic_label(item) for item in scope_path if item]
            scope_key = "category:" + " > ".join(item for item in normalized if item)
        scope_label = str(candidate.scope_label or "").strip() or " > ".join(scope_path) or label
        return scope_key, scope_label

    def _build_category_candidate_task_description(self, category_name: str) -> str:
        return self._build_expand_task_description(self._build_subtask_context(category_name))

    def _page_facts_support_grouped_split(self, result: dict) -> bool:
        if self._get_page_fact_candidates(result):
            return True
        if bool(result.get("category_controls_present")):
            return True
        if bool(result.get("supports_same_page_variant_switch")):
            return True
        return False

    def _get_page_fact_candidates(self, result: dict) -> list[dict]:
        return list(result.get("category_candidates") or [])

    def _get_analysis_candidates(self, result: dict) -> list[dict]:
        category_candidates = list(result.get("category_candidates") or [])
        if category_candidates:
            return category_candidates
        return list(result.get("subtasks") or [])

    def _set_analysis_candidates(self, result: dict, items: list[dict]) -> None:
        if "category_candidates" in result or list(result.get("category_candidates") or []):
            result["category_candidates"] = list(items)
        result["subtasks"] = list(items)

    def _extract_subtask_names(self, result: dict) -> list[str]:
        names: list[str] = []
        for item in self._get_analysis_candidates(result):
            name = str(item.get("name") or item.get("link_text") or "").strip()
            if name:
                names.append(name)
        return names

    def _is_backtrack_candidate(
        self,
        current_path: list[str],
        candidate_path: list[str],
    ) -> bool:
        if not current_path or not candidate_path:
            return False
        if len(candidate_path) == 1:
            return candidate_path[0] in current_path
        if len(candidate_path) > len(current_path):
            return False
        return current_path[: len(candidate_path)] == candidate_path

    def _looks_like_sibling_switch_group(
        self,
        current_label: str,
        candidate_names: list[str],
    ) -> bool:
        current_group, current_leaf = self._split_grouped_category_label(current_label)
        if not current_group or not current_leaf:
            return False

        normalized_current_group = self._normalize_semantic_label(current_group)
        normalized_current_leaf = self._normalize_semantic_label(current_leaf)
        if not normalized_current_group or not normalized_current_leaf:
            return False

        has_peer_candidate = False
        for name in candidate_names:
            group, leaf = self._split_grouped_category_label(name)
            normalized_group = self._normalize_semantic_label(group)
            normalized_leaf = self._normalize_semantic_label(leaf)
            if not normalized_group or not normalized_leaf:
                return False
            if normalized_group != normalized_current_group:
                return False
            if normalized_leaf != normalized_current_leaf:
                has_peer_candidate = True
        return has_peer_candidate

    def _matches_registered_sibling_switches(
        self,
        context: dict[str, str] | None,
        candidate_names: list[str],
    ) -> bool:
        current_path = self._extract_category_path(context)
        if len(current_path) < 2:
            return False

        parent_signature = self._build_parent_category_signature(current_path)
        registered = self._get_sibling_category_registry().get(parent_signature) or set()
        if len(registered) < 2:
            return False

        candidate_labels: set[str] = set()
        for name in candidate_names:
            normalized = self._normalize_category_leaf_label(name)
            if normalized:
                candidate_labels.add(normalized)
        if not candidate_labels:
            return False

        current_label = self._normalize_category_leaf_label(current_path[-1])
        return candidate_labels.issubset(registered) and any(
            label != current_label for label in candidate_labels
        )

    def _looks_like_current_category(self, name: str, analysis: dict) -> bool:
        label = str(name or "").strip()
        if not label:
            return False
        current_selected = str(analysis.get("current_selected_category") or "").strip()
        if not current_selected:
            return False
        normalized_label = self._normalize_category_leaf_label(label)
        normalized_selected = self._normalize_category_leaf_label(current_selected)
        return bool(normalized_label and normalized_label == normalized_selected)
