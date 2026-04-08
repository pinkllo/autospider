from __future__ import annotations

from ...common.utils.string_maps import normalize_string_map

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
