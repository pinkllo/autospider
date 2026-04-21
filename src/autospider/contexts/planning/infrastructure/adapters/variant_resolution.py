"""Planning adapter helpers for expanding category variants."""

from __future__ import annotations

from urllib.parse import urljoin

from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from autospider.platform.browser.som.text_first import resolve_single_mark_id
from autospider.contexts.planning.infrastructure.adapters.variant_navigation import (
    PlannerVariantNavigationMixin,
)

logger = get_logger(__name__)


class PlannerVariantResolverMixin(PlannerVariantNavigationMixin):
    def _build_planner_candidates(self, snapshot: object, max_candidates: int = 30) -> str:
        marks = getattr(snapshot, "marks", None) or []
        if not marks:
            return "无"

        interactive_roles = {"link", "tab", "menuitem", "button", "option", "treeitem"}
        candidates: list[tuple[int, str]] = []

        for mark in marks:
            text = str(getattr(mark, "text", "") or "").strip()
            aria_label = str(getattr(mark, "aria_label", "") or "").strip()
            href = str(getattr(mark, "href", "") or "").strip()
            tag = str(getattr(mark, "tag", "") or "").lower()
            role = str(getattr(mark, "role", "") or "").lower()

            if tag not in {"a", "button", "li", "div", "span"} and role not in interactive_roles:
                continue
            label = text or aria_label
            if not label:
                continue

            score = 0
            if tag == "a":
                score += 3
            if role in {"link", "tab", "menuitem"}:
                score += 2
            if href:
                score += 1
            if len(label) > 40:
                score -= 1

            line = f"- [{mark.mark_id}] {label}"
            if href:
                line += f" | href={href[:80]}"
            candidates.append((score, line))

        if not candidates:
            return "无"

        candidates.sort(key=lambda item: item[0], reverse=True)
        lines = [line for _, line in candidates[:max_candidates]]
        return "\n".join(lines) if lines else "无"

    async def _resolve_mark_id_from_link_text(self, snapshot: object, link_text: str) -> int | None:
        target = str(link_text or "").strip()
        if not target:
            return None

        marks = getattr(snapshot, "marks", None) or []
        if not marks:
            return None

        normalized_target = "".join(target.lower().split())
        exact_candidates: list[int] = []
        fuzzy_candidates: list[int] = []

        for mark in marks:
            text = str(getattr(mark, "text", "") or "").strip()
            aria_label = str(getattr(mark, "aria_label", "") or "").strip()
            haystack = " ".join([text, aria_label]).strip()
            if not haystack:
                continue
            normalized_haystack = "".join(haystack.lower().split())
            if not normalized_haystack:
                continue
            if normalized_haystack == normalized_target:
                exact_candidates.append(mark.mark_id)
            elif (
                normalized_target in normalized_haystack or normalized_haystack in normalized_target
            ):
                fuzzy_candidates.append(mark.mark_id)

        if len(exact_candidates) == 1:
            return exact_candidates[0]
        if not exact_candidates and len(fuzzy_candidates) == 1:
            return fuzzy_candidates[0]

        try:
            return await resolve_single_mark_id(
                page=self.page,
                llm=self.llm,
                snapshot=snapshot,
                mark_id=None,
                target_text=target,
                max_retries=config.url_collector.max_validation_retries,
            )
        except Exception:
            if exact_candidates:
                return exact_candidates[0]
            if fuzzy_candidates:
                return fuzzy_candidates[0]
            return None

    async def _extract_subtask_variants(
        self,
        analysis: dict,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        parent_context: dict[str, str] | None = None,
    ) -> list:
        raw_subtasks = analysis.get("subtasks", [])
        if not raw_subtasks:
            return []

        variants: list = []
        seen_signatures: set[str] = set()
        base_url = self.page.url
        original_url = self.page.url

        for idx, raw in enumerate(raw_subtasks):
            name = raw.get("name", f"分类_{idx + 1}")
            link_text = str(raw.get("link_text") or name or "").strip()
            try:
                mark_id = int(raw.get("mark_id")) if raw.get("mark_id") is not None else None
            except (TypeError, ValueError):
                mark_id = None
            if mark_id is None and link_text:
                mark_id = await self._resolve_mark_id_from_link_text(snapshot, link_text)
                if mark_id is not None:
                    logger.info("[Planner] [%s] 文本解析到 mark_id=%s", name, mark_id)

            resolved_url = ""
            variant_nav_steps = list(parent_nav_steps or [])
            same_page_variant = False
            child_context = self._build_subtask_context(name, parent_context=parent_context)

            if mark_id is not None and hasattr(snapshot, "marks"):
                for mark in snapshot.marks:
                    if mark.mark_id == mark_id and mark.href:
                        href_lower = str(mark.href).strip().lower()
                        if href_lower.startswith("javascript:") or href_lower in ("#", ""):
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 无效（已过滤）: %s",
                                name,
                                mark.href[:80],
                            )
                            break
                        resolved_url = urljoin(base_url, mark.href)
                        if (
                            resolved_url.lower() == base_url.lower()
                            or resolved_url.lower() == original_url.lower()
                        ):
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 指向当前页（已过滤）: %s",
                                name,
                                resolved_url[:80],
                            )
                            resolved_url = ""
                            break
                        logger.info(
                            "[Planner] [%s] 策略1：从 mark href 获取 URL: %s",
                            name,
                            resolved_url[:80],
                        )
                        break

            if not resolved_url and mark_id is not None:
                resolved_url = await self._get_href_by_js(
                    mark_id,
                    base_url,
                    snapshot,
                    link_text=link_text,
                )
                if resolved_url:
                    lower = resolved_url.strip().lower()
                    if (
                        lower.startswith("javascript:")
                        or lower in ("#", "")
                        or lower == base_url.lower()
                        or lower == original_url.lower()
                    ):
                        logger.info(
                            "[Planner] [%s] 策略2：JS 返回无效 URL（已过滤）: %s",
                            name,
                            resolved_url[:80],
                        )
                        resolved_url = ""
                    else:
                        logger.info(
                            "[Planner] [%s] 策略2：从 JS 属性获取 URL: %s",
                            name,
                            resolved_url[:80],
                        )

            if not resolved_url and mark_id is not None:
                resolved = await self._get_url_by_navigation(
                    mark_id,
                    original_url,
                    snapshot,
                    parent_nav_steps=parent_nav_steps,
                    variant_label=self._build_variant_label(child_context)
                    or str(name or "").strip(),
                    child_context=child_context,
                    link_text=link_text,
                )
                if resolved is not None:
                    resolved_url = resolved.resolved_url
                    variant_nav_steps = list(resolved.nav_steps or variant_nav_steps)
                    same_page_variant = resolved.same_page_variant
                    logger.info(
                        "[Planner] [%s] 策略3：解析到页面状态: %s",
                        name,
                        str(resolved.page_state_signature or resolved.resolved_url)[:80],
                    )
                elif self._looks_like_current_category(name, analysis):
                    resolved_url = original_url
                    variant_nav_steps = list(parent_nav_steps or [])
                    logger.info(
                        "[Planner] [%s] 策略3：识别为当前已选分类，直接复用当前页面状态",
                        name,
                    )

            if not resolved_url:
                logger.warning(
                    "[Planner] [%s] 无法解析分类入口状态，跳过该子任务",
                    name,
                )
                continue

            page_state_signature = self._build_page_state_signature(resolved_url, variant_nav_steps)
            if page_state_signature in seen_signatures:
                logger.warning(
                    "[Planner] [%s] 解析结果与已有状态重复，跳过重复子任务: %s",
                    name,
                    page_state_signature[:80],
                )
                continue
            seen_signatures.add(page_state_signature)
            variants.append(
                self.__class__.ResolvedPlannerVariant(
                    resolved_url=resolved_url,
                    anchor_url=original_url,
                    nav_steps=variant_nav_steps,
                    page_state_signature=page_state_signature,
                    variant_label=self._build_variant_label(child_context)
                    or str(name or "").strip(),
                    context=child_context,
                    same_page_variant=same_page_variant,
                )
            )

        return variants
