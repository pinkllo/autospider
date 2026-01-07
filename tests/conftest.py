"""pytest 全局配置和 fixtures

提供测试所需的基础设施和 Mock 对象。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ============================================================================
# 异步事件循环配置
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_page():
    """模拟 Playwright Page 对象"""
    page = AsyncMock()
    page.url = "https://example.com/list"
    page.title = AsyncMock(return_value="测试页面")
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.locator = MagicMock()
    page.locator.return_value.click = AsyncMock()
    page.locator.return_value.fill = AsyncMock()
    page.locator.return_value.count = AsyncMock(return_value=1)
    return page


@pytest.fixture
def mock_llm_response_select_links():
    """模拟 LLM 选择链接的响应"""
    return {
        "action": "select_detail_links",
        "mark_id_text_map": {
            "1": "测试项目招标公告",
            "2": "另一个项目中标公告",
        },
        "reasoning": "选择了2个项目标题链接",
    }


@pytest.fixture
def mock_llm_response_current_is_detail():
    """模拟 LLM 判断当前是详情页的响应"""
    return {
        "action": "current_is_detail",
        "reasoning": "当前页面是详情页",
    }


@pytest.fixture
def mock_llm_response_scroll():
    """模拟 LLM 要求滚动的响应"""
    return {
        "action": "scroll_down",
        "reasoning": "需要滚动查看更多内容",
    }


@pytest.fixture
def mock_llm_response_pagination():
    """模拟 LLM 分页识别响应"""
    return {
        "found": True,
        "mark_id": "42",
        "reasoning": "找到下一页按钮",
    }


@pytest.fixture
def mock_element_mark():
    """模拟 SoM 元素标记"""
    from autospider.common.types import ElementMark, BoundingBox, XPathCandidate
    
    return ElementMark(
        mark_id=1,
        tag="a",
        role="link",
        text="测试项目招标公告",
        aria_label=None,
        placeholder=None,
        href="https://example.com/detail/1",
        input_type=None,
        bbox=BoundingBox(x=100, y=200, width=300, height=30),
        center_normalized=(0.25, 0.3),
        xpath_candidates=[
            XPathCandidate(
                xpath="//a[@id='link-1']",
                priority=1,
                strategy="id",
                confidence=1.0,
            )
        ],
        is_visible=True,
        z_index=0,
    )


@pytest.fixture
def mock_som_snapshot(mock_element_mark):
    """模拟 SoM 快照"""
    from autospider.common.types import SoMSnapshot
    import time
    
    return SoMSnapshot(
        url="https://example.com/list",
        title="列表页",
        viewport_width=1280,
        viewport_height=720,
        marks=[mock_element_mark],
        screenshot_base64="",
        timestamp=time.time(),
        scroll_info=None,
    )


# ============================================================================
# 配置 Mock
# ============================================================================

@pytest.fixture
def mock_config():
    """模拟配置对象"""
    config = MagicMock()
    config.url_collector.action_delay_base = 0.1
    config.url_collector.action_delay_random = 0.0
    config.url_collector.page_load_delay = 0.1
    config.url_collector.scroll_delay = 0.1
    config.url_collector.validate_mark_id = True
    config.url_collector.mark_id_match_threshold = 0.6
    config.url_collector.max_validation_retries = 1
    config.url_collector.target_url_count = 10
    config.url_collector.max_pages = 5
    config.redis.enabled = False
    return config


# ============================================================================
# 临时目录 Fixture
# ============================================================================

@pytest.fixture
def temp_output_dir(tmp_path):
    """创建临时输出目录"""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


# ============================================================================
# Redis Mock
# ============================================================================

@pytest.fixture
def mock_redis_manager():
    """模拟 Redis 管理器"""
    manager = AsyncMock()
    manager.connect = AsyncMock(return_value=MagicMock())
    manager.load_items = AsyncMock(return_value=set())
    manager.save_item = AsyncMock(return_value=True)
    manager.save_items_batch = AsyncMock(return_value=True)
    manager.get_count = AsyncMock(return_value=0)
    manager.close = AsyncMock()
    return manager
