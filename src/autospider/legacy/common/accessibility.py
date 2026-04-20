"""Accessibility Tree 文本锚点工具。

从 Playwright 的无障碍快照中提取紧凑的层级文本，
作为截图的辅助锚点，防止 LLM 输出文本漂移。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from .logger import get_logger

logger = get_logger(__name__)

# 忽略的角色（纯装饰或无语义价值）
_SKIP_ROLES = frozenset(
    {
        "none",
        "presentation",
        "generic",
        "separator",
        "group",
    }
)

# 需要渲染状态标记的角色
_STATEFUL_ROLES = frozenset(
    {
        "tab",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "radio",
        "checkbox",
        "switch",
        "treeitem",
    }
)


async def get_accessibility_text(
    page: "Page",
    *,
    max_depth: int = 80,
    max_lines: int = 3000,
) -> str:
    """获取页面的无障碍文本锚点。

    返回紧凑的层级文本，用于辅助 LLM 精确引用页面文字。

    Args:
        page: Playwright 页面对象。
        max_depth: 最大遍历深度。
        max_lines: 最大输出行数。
    """
    try:
        tree = await page.accessibility.snapshot()
    except Exception as exc:
        logger.debug("[Accessibility] 获取快照失败: %s", exc)
        return ""

    if not tree:
        return ""

    lines: list[str] = []
    _walk(tree, depth=0, max_depth=max_depth, max_lines=max_lines, lines=lines)

    if not lines:
        return ""

    return "\n".join(lines)


def _walk(
    node: dict,
    *,
    depth: int,
    max_depth: int,
    max_lines: int,
    lines: list[str],
) -> None:
    """递归遍历无障碍树节点，生成紧凑文本。"""
    if len(lines) >= max_lines:
        return

    if depth > max_depth:
        return

    role = (node.get("role") or "").strip().lower()
    name = (node.get("name") or "").strip()
    children = node.get("children") or []

    # 跳过无语义角色（但继续遍历子节点）
    skip_self = role in _SKIP_ROLES or (not role and not name)

    if not skip_self and (role or name):
        indent = "  " * depth
        parts: list[str] = []

        # 角色
        if role and role != "text":
            parts.append(role)

        # 名称/文本
        if name:
            # 截断过长文本
            display_name = name if len(name) <= 200 else name[:197] + "..."
            parts.append(f'"{display_name}"')

        # 状态标记
        if role in _STATEFUL_ROLES:
            state_flags = _collect_state_flags(node)
            if state_flags:
                parts.append(f"[{', '.join(state_flags)}]")

        # disabled 状态（所有角色通用）
        if node.get("disabled"):
            parts.append("[disabled]")

        if parts:
            line = f"{indent}{' '.join(parts)}"
            lines.append(line)

    # 递归子节点
    for child in children:
        if len(lines) >= max_lines:
            lines.append("  ... （已截断）")
            return
        _walk(
            child,
            depth=depth if skip_self else depth + 1,
            max_depth=max_depth,
            max_lines=max_lines,
            lines=lines,
        )


def _collect_state_flags(node: dict) -> list[str]:
    """收集节点的状态标记。"""
    flags: list[str] = []
    if node.get("selected"):
        flags.append("selected")
    if node.get("expanded") is True:
        flags.append("expanded")
    elif node.get("expanded") is False:
        flags.append("collapsed")
    if node.get("checked") == "true" or node.get("checked") is True:
        flags.append("checked")
    if node.get("pressed") == "true" or node.get("pressed") is True:
        flags.append("pressed")
    return flags
