"""Planner page-state helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from autospider.platform.observability.logger import get_logger
from autospider.contexts.planning.domain.ports import NavigationStepReplayerFactory

logger = get_logger(__name__)

_ACTIVE_STATE_TOKENS = ("active", "selected", "current", "checked")
_SAME_PAGE_ROLES = {"tab", "option", "menuitem", "menuitemradio", "treeitem"}
_SAME_PAGE_TAGS = {"button"}
_EMPTY_HREF_VALUES = {"", "#", "javascript:void(0)", "javascript:void(0);", "javascript:;"}


class PlannerPageState:
    """Encapsulates planner page state normalization and replay."""

    def __init__(
        self,
        page: Any,
        navigation_replayer_factory: NavigationStepReplayerFactory | None = None,
    ) -> None:
        self.page = page
        self._navigation_replayer_factory = navigation_replayer_factory

    def _stable_xpath_candidates(self, step: dict[str, Any]) -> list[dict[str, object]]:
        xpath_candidates = step.get("clicked_element_xpath_candidates") or []
        stable_candidates: list[dict[str, object]] = []
        for candidate in xpath_candidates:
            xpath = str((candidate or {}).get("xpath") or "").strip()
            if not xpath:
                continue
            stable_candidates.append(
                {
                    "xpath": xpath,
                    "priority": (candidate or {}).get("priority"),
                    "strategy": str((candidate or {}).get("strategy") or "").strip(),
                }
            )
        return stable_candidates

    def stable_nav_step_payload(self, step: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "action": str(step.get("action") or "").strip().lower(),
            "target_text": str(step.get("target_text") or "").strip(),
            "text": str(step.get("text") or "").strip(),
            "key": str(step.get("key") or "").strip(),
            "url": str(step.get("url") or "").strip(),
            "scroll_delta": step.get("scroll_delta"),
        }

        stable_candidates = self._stable_xpath_candidates(step)
        if stable_candidates:
            payload["clicked_element_xpath_candidates"] = stable_candidates
        stable_validation = self._stable_state_validation(step)
        if stable_validation:
            payload["state_validation"] = stable_validation

        return payload

    def _stable_state_validation(self, step: dict[str, Any]) -> dict[str, str]:
        raw = step.get("state_validation")
        if not isinstance(raw, dict):
            return {}
        kind = str(raw.get("kind") or "").strip().lower()
        interaction_xpath = str(raw.get("interaction_xpath") or "").strip()
        if not kind:
            return {}
        payload = {"kind": kind}
        if interaction_xpath:
            payload["interaction_xpath"] = interaction_xpath
        return payload

    def normalize_nav_steps(self, nav_steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [self.stable_nav_step_payload(dict(step or {})) for step in nav_steps or []]

    def replay_nav_step_payload(self, step: dict[str, Any]) -> dict[str, Any]:
        payload = self.stable_nav_step_payload(step)
        payload["success"] = step.get("success") is not False
        return payload

    def normalize_replay_nav_steps(
        self,
        nav_steps: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        return [self.replay_nav_step_payload(dict(step or {})) for step in nav_steps or []]

    def build_page_state_signature(
        self,
        current_url: str,
        nav_steps: list[dict[str, Any]] | None,
    ) -> str:
        normalized_url = str(current_url or "").strip()
        normalized_steps = self.normalize_nav_steps(nav_steps)
        if not normalized_steps:
            return normalized_url

        raw = json.dumps(
            {"url": normalized_url, "nav_steps": normalized_steps},
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{normalized_url}#{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"

    async def restore_page_state(
        self,
        target_url: str,
        nav_steps: list[dict[str, Any]] | None,
    ) -> bool:
        try:
            await self.page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
            await self.page.wait_for_timeout(300)
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await self.page.wait_for_timeout(1500)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Planner] 恢复页面 anchor 失败: %s", exc)
            return False

        if not nav_steps:
            return True

        nav_replayer = self._build_navigation_replayer(target_url, nav_steps)
        replay_ok = await nav_replayer.replay_nav_steps(self.normalize_replay_nav_steps(nav_steps))
        if not self._is_replay_result_valid(replay_ok):
            logger.warning("[Planner] 恢复页面状态失败，nav_steps=%d", len(nav_steps))
            return False

        await self.page.wait_for_timeout(500)
        return True

    async def replay_nav_steps_from_current_state(
        self,
        target_url: str,
        nav_steps: list[dict[str, Any]] | None,
    ) -> bool:
        if not nav_steps:
            return True

        nav_replayer = self._build_navigation_replayer(target_url, nav_steps)
        replay_ok = await nav_replayer.replay_nav_steps(self.normalize_replay_nav_steps(nav_steps))
        if not self._is_replay_result_valid(replay_ok):
            logger.warning("[Planner] 基于当前页面重放子状态失败，nav_steps=%d", len(nav_steps))
            return False

        await self.page.wait_for_timeout(500)
        return True

    async def enter_child_state(
        self,
        current_url: str,
        child_url: str,
        child_nav_steps: list[dict[str, Any]] | None,
        current_nav_steps: list[dict[str, Any]] | None,
    ) -> bool:
        if child_url != current_url:
            try:
                await self.page.goto(child_url, wait_until="domcontentloaded", timeout=30000)
                await self.page.wait_for_timeout(1500)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Planner] 进入子 URL 失败: %s", exc)
                return False

        extra_steps = list(child_nav_steps or [])[len(list(current_nav_steps or [])) :]
        if not extra_steps:
            return True
        return await self.replay_nav_steps_from_current_state(current_url, extra_steps)

    def build_nav_click_step(self, snapshot: object, mark_id: int) -> dict[str, Any] | None:
        marks = getattr(snapshot, "marks", None) or []
        for mark in marks:
            if mark.mark_id != mark_id:
                continue
            step = {
                "action": "click",
                "mark_id": mark_id,
                "target_text": str(getattr(mark, "text", "") or "").strip(),
                "clicked_element_text": str(getattr(mark, "text", "") or "").strip(),
                "clicked_element_tag": str(getattr(mark, "tag", "") or "").strip(),
                "clicked_element_href": str(getattr(mark, "href", "") or "").strip(),
                "clicked_element_role": str(getattr(mark, "role", "") or "").strip(),
                "clicked_element_xpath_candidates": [
                    {
                        "xpath": candidate.xpath,
                        "priority": candidate.priority,
                        "strategy": candidate.strategy,
                    }
                    for candidate in (getattr(mark, "xpath_candidates", None) or [])
                    if getattr(candidate, "xpath", None)
                ],
                "success": True,
            }
            state_validation = self._build_same_page_validation(step)
            if state_validation:
                step["state_validation"] = state_validation
            return step
        return None

    def _build_navigation_replayer(
        self,
        target_url: str,
        nav_steps: list[dict[str, Any]],
    ) -> Any:
        factory = self._navigation_replayer_factory
        if factory is None:
            raise RuntimeError("planner_page_state_navigation_replayer_factory_missing")
        return factory(
            page=self.page,
            target_url=target_url,
            max_nav_steps=max(len(nav_steps), 1),
        )

    def _is_replay_result_valid(self, replay_result: Any) -> bool:
        success = getattr(replay_result, "success", None)
        if success is False:
            return False
        if success is None and not replay_result:
            return False
        required = int(getattr(replay_result, "required_validation_steps", 0) or 0)
        if required <= 0:
            return True
        validated = int(getattr(replay_result, "validated_steps", 0) or 0)
        status = str(getattr(replay_result, "validation_status", "") or "").strip().lower()
        return status == "passed" and validated >= required

    def _build_same_page_validation(self, step: dict[str, Any]) -> dict[str, str]:
        href = str(step.get("clicked_element_href") or "").strip().lower()
        if href not in _EMPTY_HREF_VALUES:
            return {}
        role = str(step.get("clicked_element_role") or "").strip().lower()
        tag = str(step.get("clicked_element_tag") or "").strip().lower()
        if role not in _SAME_PAGE_ROLES and tag not in _SAME_PAGE_TAGS:
            return {}
        xpath = self._first_xpath_candidate(step)
        if not xpath:
            return {}
        return {
            "kind": "same_page_activation",
            "interaction_xpath": xpath,
        }

    def _first_xpath_candidate(self, step: dict[str, Any]) -> str:
        candidates = sorted(
            list(step.get("clicked_element_xpath_candidates") or []),
            key=lambda item: item.get("priority", 99),
        )
        for candidate in candidates:
            xpath = str(candidate.get("xpath") or "").strip()
            if xpath:
                return xpath
        return ""

    async def get_dom_signature(self) -> str:
        try:
            text = await self.page.evaluate(
                """() => {
                    const body = document.body;
                    return body ? body.innerText.trim() : '';
                }"""
            )
            return hashlib.md5(text.encode("utf-8")).hexdigest() if text else ""
        except Exception:
            return ""

    async def get_element_interaction_state(self, xpath: str) -> dict[str, str]:
        if not xpath:
            return {}
        try:
            state = await self.page.evaluate(
                """(xpath) => {
                    const result = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    const el = result.singleNodeValue;
                    if (!el) return {};
                    return {
                        class_name: String(el.className || ''),
                        aria_selected: String(el.getAttribute('aria-selected') || ''),
                        aria_current: String(el.getAttribute('aria-current') || ''),
                        data_state: String(el.getAttribute('data-state') || ''),
                    };
                }""",
                xpath,
            )
            return dict(state or {})
        except Exception:
            return {}

    def did_interaction_state_activate(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> bool:
        return self._is_selected_state(after) and not self._is_selected_state(before)

    def _is_selected_state(self, state: dict[str, Any] | None) -> bool:
        if not state:
            return False
        class_name = str(state.get("class_name") or "").lower()
        if any(token in class_name for token in _ACTIVE_STATE_TOKENS):
            return True
        if str(state.get("aria_selected") or "").lower() == "true":
            return True
        if str(state.get("aria_current") or "").lower() in {"true", "page", "step", "location"}:
            return True
        return str(state.get("data_state") or "").lower() in _ACTIVE_STATE_TOKENS

    async def restore_original_page(self, original_url: str) -> None:
        try:
            await self.page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
            await self.page.wait_for_timeout(300)
            await self.page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
            await self.page.wait_for_timeout(2000)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Planner] 恢复原始页面失败: %s", exc)
