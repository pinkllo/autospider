"""自定义异常类

定义项目中使用的所有自定义异常，用于更精细的错误处理。
"""

from __future__ import annotations


class AutoSpiderError(Exception):
    """AutoSpider 基础异常类
    
    所有自定义异常的基类。
    """
    pass


class LLMError(AutoSpiderError):
    """LLM 相关错误的基类"""
    pass


class LLMResponseError(LLMError):
    """LLM 响应解析错误
    
    当 LLM 返回的响应无法解析为预期格式时抛出。
    """
    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class LLMTimeoutError(LLMError):
    """LLM 请求超时错误"""
    pass


class BrowserError(AutoSpiderError):
    """浏览器相关错误的基类"""
    pass


class PageLoadError(BrowserError):
    """页面加载失败
    
    当页面无法在超时时间内加载完成时抛出。
    """
    def __init__(self, url: str, message: str = "页面加载失败"):
        super().__init__(f"{message}: {url}")
        self.url = url


class ElementNotFoundError(BrowserError):
    """元素未找到错误
    
    当无法找到目标元素时抛出。
    """
    def __init__(self, selector: str, message: str = "元素未找到"):
        super().__init__(f"{message}: {selector}")
        self.selector = selector


class ElementNotClickableError(BrowserError):
    """元素不可点击错误
    
    当元素存在但无法点击时抛出。
    """
    def __init__(self, selector: str, reason: str = "元素被遮挡或不可见"):
        super().__init__(f"元素不可点击: {selector}, 原因: {reason}")
        self.selector = selector
        self.reason = reason


class ValidationError(AutoSpiderError):
    """验证失败错误"""
    pass


# class MarkIdValidationError(ValidationError):
#     """mark_id 验证失败
    
#     当 LLM 选择的 mark_id 与实际元素文本不匹配时抛出。
#     """
#     def __init__(self, mark_id: int, expected_text: str, actual_text: str | None = None):
#         message = f"mark_id {mark_id} 验证失败: 期望 '{expected_text}'"
#         if actual_text:
#             message += f", 实际 '{actual_text}'"
#         super().__init__(message)
#         self.mark_id = mark_id
#         self.expected_text = expected_text
#         self.actual_text = actual_text


class URLValidationError(ValidationError):
    """URL 验证失败"""
    def __init__(self, url: str, reason: str = "格式无效"):
        super().__init__(f"URL 验证失败: {url}, 原因: {reason}")
        self.url = url
        self.reason = reason


class StorageError(AutoSpiderError):
    """存储相关错误的基类"""
    pass


class RedisConnectionError(StorageError):
    """Redis 连接失败
    
    当无法连接到 Redis 服务器时抛出。
    """
    def __init__(self, host: str, port: int, message: str = "连接失败"):
        super().__init__(f"Redis {message}: {host}:{port}")
        self.host = host
        self.port = port


class ConfigError(AutoSpiderError):
    """配置相关错误"""
    pass


class ConfigFileNotFoundError(ConfigError):
    """配置文件未找到"""
    def __init__(self, path: str):
        super().__init__(f"配置文件未找到: {path}")
        self.path = path


class ConfigValidationError(ConfigError):
    """配置验证失败"""
    pass


class CollectionError(AutoSpiderError):
    """URL 收集相关错误"""
    pass


class NoDetailLinksFoundError(CollectionError):
    """未找到详情链接"""
    def __init__(self, page_url: str):
        super().__init__(f"页面中未找到详情链接: {page_url}")
        self.page_url = page_url


class PaginationError(CollectionError):
    """分页处理错误"""
    pass


class AntiCrawlerError(CollectionError):
    """检测到反爬虫措施"""
    def __init__(self, message: str = "检测到反爬虫措施", response_code: int | None = None):
        super().__init__(message)
        self.response_code = response_code
