"""Planning adapter helpers for navigation-based variant resolution."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from autospider.platform.observability.logger import get_logger

logger = get_logger(__name__)
_STATE_CHANGE_POLL_INTERVALS_MS = (0, 200, 300, 400, 600)


class PlannerVariantNavigationMixin:
    def _get_best_xpath_for_mark(self, snapshot: object, mark_id: int) -> str | None:
        marks = getattr(snapshot, "marks", None) or []
        for mark in marks:
            if mark.mark_id == mark_id:
                candidates = getattr(mark, "xpath_candidates", None) or []
                if candidates:
                    return candidates[0].xpath
        return None

    async def _get_href_by_js(
        self,
        mark_id: int,
        base_url: str,
        snapshot: object,
        link_text: str = "",
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
            except Exception as exc:
                logger.debug("[Planner] 文本定位获取 href 失败 ('%s'): %s", link_text, exc)

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
        except Exception as exc:
            logger.debug("[Planner] JS 执行获取 mark_id=%d 的 href 失败: %s", mark_id, exc)
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
                            "[Planner]   文本匹配定位成功: '%s' (mark_id=%d)",
                            link_text,
                            mark_id,
                        )
                        break

                if xpath:
                    xpath_locator = self.page.locator(f"xpath={xpath}")
                    if await xpath_locator.count() > 0:
                        locator = xpath_locator.first
                        logger.info(
                            "[Planner]   XPath 定位成功: mark_id=%d (xpath=%s)",
                            mark_id,
                            xpath[:60],
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
        except Exception as exc:
            logger.debug("[Planner]   模拟点击导航 mark_id=%d 失败: %s", mark_id, exc)
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
