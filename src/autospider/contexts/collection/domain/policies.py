from __future__ import annotations


class VariantResolver:
    def resolve_label(self, context: dict[str, str] | None) -> str | None:
        if not context:
            return None
        category = str(context.get("category") or "").strip()
        if category:
            return category
        scope = str(context.get("scope_label") or "").strip()
        return scope or None
