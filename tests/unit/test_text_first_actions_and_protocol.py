from __future__ import annotations

import asyncio

from autospider.common.browser import actions as actions_module
from autospider.common.browser.actions import ActionExecutor
from autospider.common.llm.decider import LLMDecider
from autospider.common.protocol import parse_protocol_message
from autospider.common.types import Action, ActionType


class _FakePage:
    def __init__(self, url: str = "https://example.com"):
        self.url = url


class _FakeLocator:
    async def click(self, timeout: int | None = None):
        _ = timeout

    async def fill(self, value: str, timeout: int | None = None):
        _ = (value, timeout)


def test_protocol_infers_click_when_only_target_text():
    parsed = parse_protocol_message({"args": {"target_text": "佛教部"}})
    assert parsed is not None
    assert parsed["action"] == "click"
    assert parsed["args"]["target_text"] == "佛教部"


def test_protocol_infers_type_when_text_and_target_text_present():
    parsed = parse_protocol_message({"args": {"text": "佛教", "target_text": "搜索"}})
    assert parsed is not None
    assert parsed["action"] == "type"
    assert parsed["args"]["target_text"] == "搜索"


def test_decider_parse_response_infers_click_from_target_text_only():
    decider = object.__new__(LLMDecider)
    action = decider._parse_response('{"args":{"target_text":"佛教部"}}')
    assert action.action == ActionType.CLICK
    assert action.target_text == "佛教部"
    assert action.mark_id is None


def test_decider_parse_response_infers_type_from_target_text_and_text():
    decider = object.__new__(LLMDecider)
    action = decider._parse_response('{"args":{"target_text":"搜索框","text":"佛教"}}')
    assert action.action == ActionType.TYPE
    assert action.target_text == "搜索框"
    assert action.text == "佛教"


def test_action_executor_click_works_with_target_text_only(monkeypatch):
    async def _fake_click_and_capture_new_page(**kwargs):
        _ = kwargs
        return None

    monkeypatch.setattr(actions_module, "click_and_capture_new_page", _fake_click_and_capture_new_page)

    executor = ActionExecutor(_FakePage())

    async def _fake_find_by_text(target_text, mark_id_to_xpath, require_fillable=False):
        _ = (target_text, mark_id_to_xpath, require_fillable)
        return _FakeLocator(), "text=佛教部", None, []

    executor._find_locator_by_target_text = _fake_find_by_text

    result, step = asyncio.run(
        executor._execute_click(
            Action(action=ActionType.CLICK, target_text="佛教部", timeout_ms=1000),
            mark_id_to_xpath={},
            step_index=1,
        )
    )
    assert result.success is True
    assert step is not None
    assert step.target_xpath == "text=佛教部"


def test_action_executor_type_works_with_target_text_only(monkeypatch):
    async def _fake_press_and_capture_new_page(**kwargs):
        _ = kwargs
        return None

    monkeypatch.setattr(actions_module, "press_and_capture_new_page", _fake_press_and_capture_new_page)

    executor = ActionExecutor(_FakePage())

    async def _fake_find_by_text(target_text, mark_id_to_xpath, require_fillable=False):
        _ = (target_text, mark_id_to_xpath, require_fillable)
        return _FakeLocator(), "text=搜索框", None, []

    executor._find_locator_by_target_text = _fake_find_by_text

    result, step = asyncio.run(
        executor._execute_type(
            Action(action=ActionType.TYPE, target_text="搜索框", text="佛教", timeout_ms=1000),
            mark_id_to_xpath={},
            step_index=2,
        )
    )
    assert result.success is True
    assert step is not None
    assert step.target_xpath == "text=搜索框"
