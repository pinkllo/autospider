"""Collection domain — planner variant resolution policies.

This mixin drives Playwright-based discovery when a planner expands a
category entry into concrete subtask variants. The behaviour (link text
resolution, URL strategies, same-page activation detection) belongs to
collection decision-making, so it lives in the collection context.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from autospider.legacy.common.som.text_first import resolve_single_mark_id

logger = get_logger(__name__)
_STATE_CHANGE_POLL_INTERVALS_MS = (0, 200, 300, 400, 600)


class PlannerVariantResolverMixin:
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

        candidates.sort(key=lambda x: x[0], reverse=True)
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
                    mark_id, base_url, snapshot, link_text=link_text
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
                            "[Planner] [%s] 策略2：从 JS 属性获取 URL: %s", name, resolved_url[:80]
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

    def _get_best_xpath_for_mark(self, snapshot: object, mark_id: int) -> str | None:
        marks = getattr(snapshot, "marks", None) or []
        for mark in marks:
            if mark.mark_id == mark_id:
                candidates = getattr(mark, "xpath_candidates", None) or []
                if candidates:
                    return candidates[0].xpath
        return None

    async def _get_href_by_js(
        self, mark_id: int, base_url: str, snapshot: object, link_text: str = ""
    ) -> str:
        if link_text:
            try:
                text_locator = self.page.get_by_text(link_text, exact=True)
                if await text_locator.count() > 0:
                    href = await text_locator.first.evaluate(
                        """el => {
                        if (el.href) return el.href;
                        const anchor = el.closest('a');
                        if (anchor && anchor.href) return anchor.href;
                        return null;
                    }"""
                    )
                    if href:
                        return urljoin(base_url, href)
            except Exception as e:
                logger.debug("[Planner] 文本定位获取 href 失败 ('%s'): %s", link_text, e)

        xpath = self._get_best_xpath_for_mark(snapshot, mark_id)
        if not xpath:
            return ""
        try:
            href = await self.page.evaluate(
                """(xpath) => {
                    const result = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    const el = result.singleNodeValue;
                    if (!el) return null;
                    if (el.href) return el.href;
                    const anchor = el.closest('a');
                    if (anchor && anchor.href) return anchor.href;
                    return null;
                }""",
                xpath,
            )
            if href:
                return urljoin(base_url, href)
        except Exception as e:
            logger.debug("[Planner] JS 执行获取 mark_id=%d 的 href 失败: %s", mark_id, e)
        return ""

    async def _get_url_by_navigation(
        self,
        mark_id: int,
        original_url: str,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        variant_label: str = "",
        child_context: dict[str, str] | None = None,
        link_text: str = "",
    ):
        xpath = self._get_best_xpath_for_mark(snapshot, mark_id)

        nav_step_record = self._build_nav_click_step(snapshot, mark_id)
        if not nav_step_record:
            logger.debug("[Planner]   mark_id=%d 无法构造导航回放动作", mark_id)
            return None

        try:
            locator = None
            for attempt in range(2):
                if link_text:
                    text_locator = self.page.get_by_text(link_text, exact=True)
                    if await text_locator.count() > 0:
                        locator = text_locator.first
                        logger.info(
                            "[Planner]   文本匹配定位成功: '%s' (mark_id=%d)", link_text, mark_id
                        )
                        break

                if xpath:
                    xpath_locator = self.page.locator(f"xpath={xpath}")
                    if await xpath_locator.count() > 0:
                        locator = xpath_locator.first
                        logger.info(
                            "[Planner]   XPath 定位成功: mark_id=%d (xpath=%s)", mark_id, xpath[:60]
                        )
                        break

                if attempt == 0:
                    logger.info("[Planner]   首次定位失败，等待页面渲染后重试...")
                    await self.page.wait_for_timeout(2000)

            if locator is None:
                logger.warning(
                    "[Planner]   文本('%s')和 XPath 均未匹配到元素, mark_id=%d",
                    link_text or "(无)",
                    mark_id,
                )
                return None

            url_before = self.page.url
            dom_sig_before = await self._get_dom_signature()
            interaction_state_before = (
                await self._get_element_interaction_state(xpath) if xpath else {}
            )

            await locator.click(timeout=5000)

            url_after = self.page.url
            old_parsed = urlparse(url_before)
            new_parsed = urlparse(url_after)
            url_changed = url_after != url_before or old_parsed.fragment != new_parsed.fragment

            logger.info(
                "[Planner]   URL 比较: before=%s | after=%s | fragment: %s -> %s | changed=%s",
                url_before[:80],
                url_after[:80],
                old_parsed.fragment[:40] if old_parsed.fragment else "(none)",
                new_parsed.fragment[:40] if new_parsed.fragment else "(none)",
                url_changed,
            )

            if url_changed and url_after:
                await self._restore_page_state(original_url, parent_nav_steps)
                nav_steps = list(parent_nav_steps or [])
                return self.__class__.ResolvedPlannerVariant(
                    resolved_url=url_after,
                    anchor_url=url_after,
                    nav_steps=nav_steps,
                    page_state_signature=self._build_page_state_signature(url_after, nav_steps),
                    variant_label=variant_label,
                    context=self._sanitize_context(child_context),
                    same_page_variant=False,
                )

            same_page_variant = await self._resolve_same_page_variant_after_click(
                xpath=xpath or "",
                url_before=url_before,
                original_url=original_url,
                parent_nav_steps=parent_nav_steps,
                nav_step_record=nav_step_record,
                variant_label=variant_label,
                child_context=child_context,
                dom_sig_before=dom_sig_before,
                interaction_state_before=interaction_state_before,
            )
            if same_page_variant is not None:
                return same_page_variant

            logger.info("[Planner]   模拟点击后 URL 和 DOM 均未发生显著变化")
        except Exception as e:
            logger.debug("[Planner]   模拟点击导航 mark_id=%d 失败: %s", mark_id, e)
            await self._restore_page_state(original_url, parent_nav_steps)

        return None

    async def _resolve_same_page_variant_after_click(
        self,
        *,
        xpath: str,
        url_before: str,
        original_url: str,
        parent_nav_steps: list[dict] | None,
        nav_step_record: dict,
        variant_label: str,
        child_context: dict[str, str] | None,
        dom_sig_before: str,
        interaction_state_before: dict[str, str] | None,
    ):
        elapsed_ms = 0
        for wait_ms in _STATE_CHANGE_POLL_INTERVALS_MS:
            if wait_ms:
                await self.page.wait_for_timeout(wait_ms)
                elapsed_ms += wait_ms
            dom_sig_after = await self._get_dom_signature()
            interaction_state_after = await self._get_element_interaction_state(xpath)
            dom_changed = bool(dom_sig_after and dom_sig_after != dom_sig_before)
            state_changed = self._did_interaction_state_activate(
                interaction_state_before,
                interaction_state_after,
            )
            logger.info(
                "[Planner]   同页状态检测: waited=%sms | dom_changed=%s | state_changed=%s",
                elapsed_ms,
                dom_changed,
                state_changed,
            )
            if not dom_changed and not state_changed:
                continue

            child_nav_steps = list(parent_nav_steps or []) + [nav_step_record]
            await self._restore_page_state(original_url, parent_nav_steps)
            return self.__class__.ResolvedPlannerVariant(
                resolved_url=url_before,
                anchor_url=original_url,
                nav_steps=child_nav_steps,
                page_state_signature=self._build_page_state_signature(url_before, child_nav_steps),
                variant_label=variant_label,
                context=self._sanitize_context(child_context),
                same_page_variant=True,
            )
        return None
