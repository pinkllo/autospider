"""通用 Prompt 模板引擎。

提供纯函数接口，用于加载和渲染 YAML 格式的提示词模板。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_JINJA2_ENV = None
try:
    import jinja2

    _JINJA2_ENV = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False)
except ImportError:
    _JINJA2_ENV = None

_SHARED_RULES_PATH = str(Path(__file__).resolve().parents[3] / "prompts" / "_shared.yaml")


def is_jinja2_available() -> bool:
    """检查当前环境是否支持 Jinja2 模板引擎。"""
    return _JINJA2_ENV is not None


@lru_cache(maxsize=64)
def load_template_file(file_path: str) -> dict[str, Any]:
    """加载并缓存 YAML 模板文件。"""
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_template_cache() -> None:
    """清除模板文件缓存。"""
    load_template_file.cache_clear()


def render_text(text: str, variables: dict[str, Any] | None = None) -> str:
    """渲染模板文本。"""
    if not variables:
        return text

    if _JINJA2_ENV is not None:
        template = _JINJA2_ENV.from_string(text)
        return template.render(**variables)

    result = text
    for key, value in variables.items():
        placeholder = "{{" + str(key) + "}}"
        result = result.replace(placeholder, str(value))
    return result


def render_shared_rules(section_names: list[str] | tuple[str, ...]) -> str:
    """从 _shared.yaml 加载指定的公共规则片段并拼接。"""
    if not section_names:
        return ""
    try:
        data = load_template_file(_SHARED_RULES_PATH)
    except FileNotFoundError:
        return ""
    parts: list[str] = []
    for name in section_names:
        content = data.get(name, "")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
    return "\n\n".join(parts)


def render_template(
    file_path: str,
    section: str | None = None,
    variables: dict[str, Any] | None = None,
    *,
    append_shared: list[str] | tuple[str, ...] | None = None,
) -> str:
    """加载 YAML 模板并渲染指定 section。

    Args:
        append_shared: 可选，从 _shared.yaml 追加指定的公共规则片段名称列表。
    """
    data = load_template_file(file_path)

    if section is not None:
        content = data.get(section, "")
        if not isinstance(content, str):
            content = yaml.dump(content, allow_unicode=True, default_flow_style=False)
    else:
        content = yaml.dump(data, allow_unicode=True, default_flow_style=False)

    rendered = render_text(content, variables)

    if append_shared:
        shared = render_shared_rules(append_shared)
        if shared:
            rendered = rendered.rstrip() + "\n\n" + shared

    return rendered


def get_template_sections(file_path: str) -> list[str]:
    """获取模板文件中所有一级 key。"""
    data = load_template_file(file_path)
    return list(data.keys()) if isinstance(data, dict) else []
