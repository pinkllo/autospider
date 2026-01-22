"""SoM (Set-of-Mark) Python API"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from ..types import BoundingBox, ElementMark, ScrollInfo, SoMSnapshot, XPathCandidate

if TYPE_CHECKING:
    from playwright.async_api import Page

# 读取注入脚本
_INJECT_JS_PATH = Path(__file__).parent / "inject.js"
_INJECT_JS: str | None = None


def _get_inject_js() -> str:
    """延迟加载注入脚本"""
    global _INJECT_JS
    if _INJECT_JS is None:
        _INJECT_JS = _INJECT_JS_PATH.read_text(encoding="utf-8")
    return _INJECT_JS


async def inject_and_scan(page: "Page") -> SoMSnapshot:
    """
    注入 SoM 脚本并扫描页面

    返回带有标注的 SoMSnapshot
    """
    js_code = _get_inject_js()

    # 执行注入脚本
    result = await page.evaluate(js_code)

    # 解析结果
    marks = []
    for mark_data in result.get("marks", []):
        # 解析 XPath 候选
        xpath_candidates = [
            XPathCandidate(
                xpath=c["xpath"],
                priority=c["priority"],
                strategy=c["strategy"],
                confidence=c.get("confidence", 1.0),
            )
            for c in mark_data.get("xpath_candidates", [])
        ]

        # 解析边界框
        bbox_data = mark_data["bbox"]
        bbox = BoundingBox(
            x=bbox_data["x"],
            y=bbox_data["y"],
            width=bbox_data["width"],
            height=bbox_data["height"],
        )

        # 创建 ElementMark
        mark = ElementMark(
            mark_id=mark_data["mark_id"],
            tag=mark_data["tag"],
            role=mark_data.get("role"),
            text=mark_data.get("text", ""),
            aria_label=mark_data.get("aria_label"),
            placeholder=mark_data.get("placeholder"),
            href=mark_data.get("href"),
            input_type=mark_data.get("input_type"),
            clickability_reason=mark_data.get("clickability_reason"),
            clickability_confidence=mark_data.get("clickability_confidence"),
            bbox=bbox,
            center_normalized=tuple(mark_data.get("center_normalized", [0.5, 0.5])),
            xpath_candidates=xpath_candidates,
            is_visible=mark_data.get("is_visible", True),
            z_index=mark_data.get("z_index", 0),
        )
        marks.append(mark)

    # 解析滚动信息
    scroll_info = None
    if "scroll_info" in result and result["scroll_info"]:
        scroll_data = result["scroll_info"]
        scroll_info = ScrollInfo(
            scroll_top=scroll_data.get("scroll_top", 0),
            scroll_height=scroll_data.get("scroll_height", 0),
            client_height=scroll_data.get("client_height", 0),
            scroll_percent=scroll_data.get("scroll_percent", 0),
            is_at_top=scroll_data.get("is_at_top", True),
            is_at_bottom=scroll_data.get("is_at_bottom", False),
            can_scroll_down=scroll_data.get("can_scroll_down", True),
            can_scroll_up=scroll_data.get("can_scroll_up", False),
        )

    # 创建快照
    snapshot = SoMSnapshot(
        url=result["url"],
        title=result["title"],
        viewport_width=result["viewport_width"],
        viewport_height=result["viewport_height"],
        marks=marks,
        timestamp=result["timestamp"],
        scroll_info=scroll_info,
    )

    return snapshot


async def capture_screenshot_with_marks(page: "Page") -> tuple[bytes, str]:
    """
    截图（包含 SoM 标注框）

    返回: (screenshot_bytes, base64_encoded)
    """
    screenshot_bytes = await page.screenshot(full_page=False)
    screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    return screenshot_bytes, screenshot_base64


async def capture_screenshot_with_custom_marks(
    page: "Page",
    marks: list[dict],
    *,
    hide_original_som: bool = True,
) -> tuple[bytes, str]:
    """截图（使用自定义标注框）

    修改原因：全项目需要在“文本命中多个候选”时，把候选元素重新编号并截图给 LLM 重选，
    且不能破坏原本的 SoM data-som-id 绑定与后续点击逻辑。

    Args:
        page: Playwright 页面对象
        marks: [{"mark_id": "1", "bbox": {"x":..,"y":..,"width":..,"height":..}}, ...]
        hide_original_som: 是否隐藏原 SoM 覆盖层（避免双重标注干扰）

    Returns:
        (screenshot_bytes, base64_encoded)
    """
    container_id = "__som_custom_overlay_container__"

    js_draw = r"""
    (payload) => {
      const { containerId, marks, hideOriginal } = payload || {};

      const remove = (id) => {
        const existing = document.getElementById(id);
        if (existing) existing.remove();
      };

      // 清理旧的自定义覆盖层
      remove(containerId);

      // 隐藏原 SoM 覆盖层（不清除 data-som-id）
      if (hideOriginal) {
        try {
          if (window.__SOM__ && window.__SOM__.setVisibility) window.__SOM__.setVisibility(false);
        } catch (e) {}
        const som = document.getElementById('__som_overlay_container__');
        if (som) som.style.display = 'none';
      }

      const container = document.createElement('div');
      container.id = containerId;
      container.style.cssText = `
        position: fixed; top: 0; left: 0;
        width: 100vw; height: 100vh;
        pointer-events: none;
        z-index: 2147483647;
        overflow: hidden;
      `;
      document.body.appendChild(container);

      const labelStyle = {
        fontSize: '11px',
        fontWeight: 'bold',
        fontFamily: 'Arial, sans-serif',
        color: '#ffffff',
        backgroundColor: '#ff0000',
        padding: '1px 4px',
        borderRadius: '3px',
        zIndex: '2147483647',
      };

      const boxStyle = {
        border: '2px solid #ff0000',
        backgroundColor: 'rgba(255, 0, 0, 0.1)',
        zIndex: '2147483646',
      };

      for (const m of (marks || [])) {
        const bbox = m.bbox || {};
        const mark_id = m.mark_id || '';

        const box = document.createElement('div');
        box.style.cssText = `
          position: fixed;
          left: ${bbox.x}px; top: ${bbox.y}px;
          width: ${bbox.width}px; height: ${bbox.height}px;
          border: ${boxStyle.border};
          background-color: ${boxStyle.backgroundColor};
          pointer-events: none; box-sizing: border-box;
          z-index: ${boxStyle.zIndex};
        `;

        let labelLeft = (bbox.x || 0) + (bbox.width || 0) - 5;
        let labelTop = (bbox.y || 0) - 16;
        if (labelTop < 0) labelTop = (bbox.y || 0) + 2;
        if (labelLeft + 30 > window.innerWidth) labelLeft = (bbox.x || 0) + (bbox.width || 0) - 30;

        const label = document.createElement('div');
        label.textContent = mark_id;
        label.style.cssText = `
          position: fixed;
          left: ${labelLeft}px; top: ${labelTop}px;
          font-size: ${labelStyle.fontSize};
          font-weight: ${labelStyle.fontWeight};
          font-family: ${labelStyle.fontFamily};
          color: ${labelStyle.color};
          background-color: ${labelStyle.backgroundColor};
          padding: ${labelStyle.padding};
          border-radius: ${labelStyle.borderRadius};
          pointer-events: none;
          z-index: ${labelStyle.zIndex};
          white-space: nowrap;
        `;

        container.appendChild(box);
        container.appendChild(label);
      }
    }
    """

    js_clear = """
    (payload) => {
      const { containerId, showOriginal } = payload || {};
      const existing = document.getElementById(containerId);
      if (existing) existing.remove();

      if (showOriginal) {
        try {
          if (window.__SOM__ && window.__SOM__.setVisibility) window.__SOM__.setVisibility(true);
        } catch (e) {}
        const som = document.getElementById('__som_overlay_container__');
        if (som) som.style.display = 'block';
      }
    }
    """

    await page.evaluate(
        js_draw,
        {
            "containerId": container_id,
            "marks": marks,
            "hideOriginal": bool(hide_original_som),
        },
    )

    try:
        screenshot_bytes = await page.screenshot(full_page=False)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        return screenshot_bytes, screenshot_base64
    finally:
        await page.evaluate(
            js_clear,
            {
                "containerId": container_id,
                "showOriginal": bool(hide_original_som),
            },
        )


async def clear_overlay(page: "Page") -> None:
    """清除 SoM 覆盖层"""
    await page.evaluate("window.__SOM__?.clear()")


async def set_overlay_visibility(page: "Page", visible: bool) -> None:
    """设置覆盖层可见性"""
    await page.evaluate(f"window.__SOM__?.setVisibility({str(visible).lower()})")


async def get_element_by_mark_id(page: "Page", mark_id: int):
    """根据 mark_id 获取元素定位器"""
    return page.locator(f'[data-som-id="{mark_id}"]')


def build_mark_id_to_xpath_map(snapshot: SoMSnapshot) -> dict[int, list[str]]:
    """
    构建 mark_id 到 xpath 列表的映射

    返回的 xpath 列表按稳定性排序（最稳定的在前）
    """
    mapping = {}
    for mark in snapshot.marks:
        xpaths = [c.xpath for c in mark.xpath_candidates]
        if xpaths:
            mapping[mark.mark_id] = xpaths
        else:
            # 兜底：使用 data-som-id 属性
            mapping[mark.mark_id] = [f'//*[@data-som-id="{mark.mark_id}"]']
    return mapping


def format_marks_for_llm(snapshot: SoMSnapshot, max_marks: int = 50) -> str:
    """
    格式化 marks 信息供 LLM 使用

    返回紧凑的文本格式，便于 LLM 理解
    """
    lines = []
    for mark in snapshot.marks[:max_marks]:
        parts = [f"[{mark.mark_id}]", mark.tag]

        if mark.role:
            parts.append(f"role={mark.role}")
        if mark.text:
            text = mark.text[:30] + "..." if len(mark.text) > 30 else mark.text
            parts.append(f'"{text}"')
        if mark.aria_label:
            parts.append(f"aria-label={mark.aria_label[:20]}")
        if mark.placeholder:
            parts.append(f"placeholder={mark.placeholder[:20]}")
        if mark.href:
            href = mark.href[:30] + "..." if len(mark.href) > 30 else mark.href
            parts.append(f"href={href}")
        if mark.input_type:
            parts.append(f"type={mark.input_type}")

        # 添加归一化坐标（帮助 LLM 定位）
        cx, cy = mark.center_normalized
        parts.append(f"@({cx:.2f},{cy:.2f})")

        lines.append(" ".join(parts))

    if len(snapshot.marks) > max_marks:
        lines.append(f"... 和其他 {len(snapshot.marks) - max_marks} 个元素")

    return "\n".join(lines)
