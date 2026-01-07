"""输入验证工具

提供 URL、任务描述等用户输入的验证功能。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .constants import (
    MAX_TASK_DESCRIPTION_LENGTH,
    MAX_URL_LENGTH,
    VALID_URL_SCHEMES,
)
from .exceptions import URLValidationError, ValidationError


def validate_url(url: str, allow_empty: bool = False) -> str:
    """验证并清理 URL
    
    Args:
        url: 待验证的 URL 字符串
        allow_empty: 是否允许空 URL
        
    Returns:
        清理后的 URL
        
    Raises:
        URLValidationError: 当 URL 格式无效时
    """
    # 清理空白字符
    url = url.strip() if url else ""
    
    if not url:
        if allow_empty:
            return ""
        raise URLValidationError("", "URL 不能为空")
    
    # 检查长度
    if len(url) > MAX_URL_LENGTH:
        raise URLValidationError(url, f"URL 长度超过 {MAX_URL_LENGTH} 字符")
    
    # 解析 URL
    try:
        result = urlparse(url)
    except Exception as e:
        raise URLValidationError(url, f"URL 解析失败: {e}")
    
    # 验证 scheme
    if not result.scheme:
        raise URLValidationError(url, "缺少协议 (http/https)")
    
    if result.scheme.lower() not in VALID_URL_SCHEMES:
        raise URLValidationError(url, f"不支持的协议: {result.scheme}")
    
    # 验证 netloc
    if not result.netloc:
        raise URLValidationError(url, "缺少域名")
    
    return url


def validate_task_description(
    task: str,
    max_length: int = MAX_TASK_DESCRIPTION_LENGTH,
) -> str:
    """验证并清理任务描述
    
    Args:
        task: 任务描述文本
        max_length: 最大长度限制
        
    Returns:
        清理后的任务描述
        
    Raises:
        ValidationError: 当任务描述无效时
    """
    if not task or not task.strip():
        raise ValidationError("任务描述不能为空")
    
    task = task.strip()
    
    if len(task) > max_length:
        raise ValidationError(f"任务描述不能超过 {max_length} 字符")
    
    # 检查是否包含危险字符（防止注入）
    dangerous_patterns = [
        r"<script",
        r"javascript:",
        r"data:text/html",
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, task, re.IGNORECASE):
            raise ValidationError("任务描述包含不允许的内容")
    
    return task


def validate_positive_integer(
    value: int,
    name: str,
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    """验证正整数参数
    
    Args:
        value: 待验证的值
        name: 参数名称（用于错误消息）
        min_value: 最小值（包含）
        max_value: 最大值（包含），None 表示无上限
        
    Returns:
        验证后的值
        
    Raises:
        ValidationError: 当值无效时
    """
    if not isinstance(value, int):
        raise ValidationError(f"{name} 必须是整数")
    
    if value < min_value:
        raise ValidationError(f"{name} 必须至少为 {min_value}")
    
    if max_value is not None and value > max_value:
        raise ValidationError(f"{name} 不能超过 {max_value}")
    
    return value


def validate_file_path(path: str, must_exist: bool = True) -> str:
    """验证文件路径
    
    Args:
        path: 文件路径
        must_exist: 是否必须存在
        
    Returns:
        验证后的路径
        
    Raises:
        ValidationError: 当路径无效时
    """
    from pathlib import Path
    
    if not path or not path.strip():
        raise ValidationError("文件路径不能为空")
    
    path = path.strip()
    p = Path(path)
    
    if must_exist and not p.exists():
        raise ValidationError(f"文件不存在: {path}")
    
    if must_exist and not p.is_file():
        raise ValidationError(f"路径不是文件: {path}")
    
    return str(p.resolve())


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除不安全字符
    
    Args:
        filename: 原始文件名
        
    Returns:
        安全的文件名
    """
    # 移除路径分隔符和其他危险字符
    unsafe_chars = r'[<>:"/\\|?*\x00-\x1f]'
    safe_name = re.sub(unsafe_chars, "_", filename)
    
    # 移除首尾空白和点
    safe_name = safe_name.strip(". ")
    
    # 确保不为空
    if not safe_name:
        safe_name = "unnamed"
    
    # 限制长度
    if len(safe_name) > 200:
        safe_name = safe_name[:200]
    
    return safe_name
