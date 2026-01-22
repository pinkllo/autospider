"""
通用 Prompt 模板引擎

提供纯函数接口，用于加载和渲染 YAML 格式的提示词模板。
适用于项目中所有需要动态 Prompt 的智能体模块。

特性：
- Jinja2 优先：若安装了 jinja2，则启用全部模板功能（循环、条件等）
- 优雅降级：若未安装 jinja2，自动回退到简单的 {{key}} 占位符替换
- 路径透明：所有路径由调用方传入，无任何默认路径假设
"""

import yaml
from typing import Any
from functools import lru_cache

# --- Jinja2 环境检测 ---
# 模块加载时一次性判断 Jinja2 是否可用，避免重复 import 开销
_JINJA2_ENV = None
try:
    import jinja2

    # autoescape=False 防止对 Prompt 内容进行 HTML 转义
    _JINJA2_ENV = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False)
except ImportError:
    _JINJA2_ENV = None


def is_jinja2_available() -> bool:
    """检查当前环境是否支持 Jinja2 模板引擎。"""
    return _JINJA2_ENV is not None


@lru_cache(maxsize=64)
def load_template_file(file_path: str) -> dict[str, Any]:
    """
    加载并缓存 YAML 模板文件。

    使用 LRU 缓存，同一文件路径只会被读取一次，显著提升高频调用场景性能。
    注意：缓存依据是路径字符串，因此路径需标准化（建议使用绝对路径）。

    Args:
        file_path: YAML 模板文件的完整路径（绝对路径或相对于 CWD 的路径）

    Returns:
        YAML 文件解析后的字典对象
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_template_cache() -> None:
    """
    清除模板文件的 LRU 缓存。

    适用于开发调试场景，当模板文件内容更新后调用此函数生效。
    """
    load_template_file.cache_clear()


def render_text(text: str, variables: dict[str, Any] | None = None) -> str:
    """
    渲染一段模板文本。

    Args:
        text: 包含占位符 (如 {{name}}) 的原始文本
        variables: 变量字典，用于替换模板中的占位符

    Returns:
        渲染后的完整文本
    """
    if not variables:
        return text

    if _JINJA2_ENV is not None:
        # Jinja2 模式：支持完整模板语法（循环、条件、过滤器等）
        template = _JINJA2_ENV.from_string(text)
        return template.render(**variables)
    else:
        # 降级模式：简单字符串替换
        result = text
        for key, value in variables.items():
            placeholder = "{{" + str(key) + "}}"
            result = result.replace(placeholder, str(value))
        return result


def render_template(
    file_path: str, section: str | None = None, variables: dict[str, Any] | None = None
) -> str:
    """
    加载 YAML 模板文件并渲染指定部分。

    这是最核心的对外接口，一步完成「加载 -> 提取 -> 渲染」流程。

    Args:
        file_path: YAML 模板文件的完整路径
        section: 要渲染的 YAML 一级 Key（如 'system_prompt', 'user_prompt'）；
                 若为 None，则将整个 YAML 内容序列化为字符串并渲染
        variables: 变量字典

    Returns:
        渲染后的 Prompt 文本

    Examples:
        >>> # 渲染模板文件中的 system_prompt 部分
        >>> prompt = render_template(
        ...     "prompts/extract_selectors.yaml",
        ...     section="system_prompt",
        ...     variables={"html_content": "<div>...</div>"}
        ... )

        >>> # 渲染整个模板（不指定 section）
        >>> full = render_template("prompts/simple.yaml", variables={"name": "test"})
    """
    data = load_template_file(file_path)

    if section is not None:
        # 提取指定 Section 的内容
        content = data.get(section, "")
        if not isinstance(content, str):
            # 若 section 内容不是字符串（如嵌套结构），转为 YAML 字符串
            content = yaml.dump(content, allow_unicode=True, default_flow_style=False)
    else:
        # 无 section 时，将整个 dict 序列化为字符串
        content = yaml.dump(data, allow_unicode=True, default_flow_style=False)

    return render_text(content, variables)


def get_template_sections(file_path: str) -> list[str]:
    """
    获取模板文件中所有可用的 Section 名称（一级 Key 列表）。

    用于枚举模板文件结构，便于动态选择 Section。

    Args:
        file_path: YAML 模板文件路径

    Returns:
        该模板文件的所有一级 Key 列表
    """
    data = load_template_file(file_path)
    return list(data.keys()) if isinstance(data, dict) else []
