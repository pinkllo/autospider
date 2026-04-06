from __future__ import annotations


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
        if not self._is_multicategory_request():
            return normalized
        if self._extract_category_path(current_context):
            return normalized

        page_type = str(normalized.get("page_type") or "").strip().lower()
        requested_subtasks = self._build_requested_category_subtasks(snapshot)
        if not requested_subtasks:
            return normalized

        existing_subtasks = list(normalized.get("subtasks") or [])
        if page_type == "category" and existing_subtasks:
            return normalized

        normalized["page_type"] = "category"
        normalized["subtasks"] = requested_subtasks
        note = "检测到用户请求为多分类任务，按页面中可见分类入口强制拆分子任务。"
        return self._append_observation_note(normalized, note)

    def _prune_backtrack_subtasks(
        self,
        result: dict,
        context: dict[str, str] | None,
    ) -> dict:
        normalized = dict(result or {})
        subtasks = list(normalized.get("subtasks") or [])
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

        normalized["subtasks"] = filtered_subtasks
        if filtered_subtasks:
            note = f"已过滤祖先/当前分类回跳入口: {'; '.join(removed_names)}"
            return self._append_observation_note(normalized, note)

        normalized["page_type"] = "list_page"
        note = f"候选分类仅包含祖先或当前分类回跳入口，停止继续拆分: {'; '.join(removed_names)}"
        normalized["subtasks"] = []
        if not str(normalized.get("task_description") or "").strip():
            current_label = current_path[-1]
            normalized["task_description"] = (
                f"采集当前“{current_label}”分类下前 10 条招标/采购项目记录，"
                "提取项目名称与所属分类名称。"
            )
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
        normalized["subtasks"] = []
        normalized["task_description"] = (
            f"采集当前“{display_label}”分类下前 10 条招标/采购项目记录，"
            "提取项目名称与所属分类名称。"
        )
        note = (
            "检测到当前页面已进入具体分类，页面中剩余候选项属于同层兄弟分类切换，"
            "不再继续向下拆分。"
        )
        return self._append_observation_note(normalized, note)

    def _is_multicategory_request(self) -> bool:
        request = str(self.user_request or "").strip()
        if not request:
            return False
        keywords = (
            "每类",
            "各类",
            "各个相关分类",
            "各分类",
            "分别采集",
            "分类下",
        )
        return any(keyword in request for keyword in keywords)

    def _build_requested_category_subtasks(self, snapshot: object) -> list[dict]:
        marks = getattr(snapshot, "marks", None) or []
        request = str(self.user_request or "").strip()
        if not marks or not request:
            return []

        subtasks: list[dict] = []
        seen_labels: set[str] = set()
        interactive_roles = {"link", "tab", "menuitem", "button", "option", "treeitem"}
        for mark in marks:
            tag = str(getattr(mark, "tag", "") or "").strip().lower()
            role = str(getattr(mark, "role", "") or "").strip().lower()
            if tag not in {"a", "button", "li", "div", "span"} and role not in interactive_roles:
                continue

            label = str(getattr(mark, "text", "") or getattr(mark, "aria_label", "") or "").strip()
            if not self._is_requested_category_label(label, request):
                continue
            if label in seen_labels:
                continue
            seen_labels.add(label)
            subtasks.append(
                {
                    "name": label,
                    "mark_id": int(getattr(mark, "mark_id")),
                    "link_text": label,
                    "estimated_pages": None,
                    "task_description": self._build_requested_category_task_description(label),
                }
            )
        return subtasks

    def _is_requested_category_label(self, label: str, request: str) -> bool:
        text = str(label or "").strip()
        if not text:
            return False
        if len(text) > 12:
            return False
        if any(ch.isdigit() for ch in text):
            return False
        if text not in request:
            return False
        noise_tokens = ("项目", "名称", "网站", "分类", "招标", "采购")
        return text not in noise_tokens

    def _build_requested_category_task_description(self, category_name: str) -> str:
        return (
            f"进入“{category_name}”分类，采集该分类下前 10 条招标/采购项目记录，"
            "提取项目名称与所属分类名称。"
        )

    def _extract_subtask_names(self, result: dict) -> list[str]:
        names: list[str] = []
        for item in list(result.get("subtasks") or []):
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
        observations = str(analysis.get("observations") or "").strip()
        if not observations:
            return False
        selected_markers = ("当前选中", "当前高亮", "默认", "已选中")
        return label in observations and any(marker in observations for marker in selected_markers)
