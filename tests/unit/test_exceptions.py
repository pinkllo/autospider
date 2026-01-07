"""异常类单元测试"""

import pytest
from autospider.common.exceptions import (
    AutoSpiderError,
    LLMError,
    LLMResponseError,
    BrowserError,
    PageLoadError,
    ElementNotFoundError,
    ValidationError,
    MarkIdValidationError,
    URLValidationError,
    StorageError,
    RedisConnectionError,
    ConfigError,
    ConfigFileNotFoundError,
    CollectionError,
    NoDetailLinksFoundError,
    AntiCrawlerError,
)


class TestExceptionHierarchy:
    """异常类层次结构测试"""
    
    def test_base_exception(self):
        """测试基础异常"""
        with pytest.raises(AutoSpiderError):
            raise AutoSpiderError("基础错误")
    
    def test_llm_error_inheritance(self):
        """测试 LLM 错误继承关系"""
        error = LLMResponseError("解析失败", raw_response="invalid json")
        assert isinstance(error, LLMError)
        assert isinstance(error, AutoSpiderError)
        assert error.raw_response == "invalid json"
    
    def test_browser_error_inheritance(self):
        """测试浏览器错误继承关系"""
        error = PageLoadError("https://example.com")
        assert isinstance(error, BrowserError)
        assert isinstance(error, AutoSpiderError)
        assert error.url == "https://example.com"
    
    def test_validation_error_inheritance(self):
        """测试验证错误继承关系"""
        error = MarkIdValidationError(1, "期望文本", "实际文本")
        assert isinstance(error, ValidationError)
        assert isinstance(error, AutoSpiderError)
        assert error.mark_id == 1
        assert error.expected_text == "期望文本"
        assert error.actual_text == "实际文本"
    
    def test_storage_error_inheritance(self):
        """测试存储错误继承关系"""
        error = RedisConnectionError("localhost", 6379)
        assert isinstance(error, StorageError)
        assert isinstance(error, AutoSpiderError)
        assert error.host == "localhost"
        assert error.port == 6379


class TestExceptionMessages:
    """异常消息测试"""
    
    def test_page_load_error_message(self):
        """测试页面加载错误消息"""
        error = PageLoadError("https://example.com", "超时")
        assert "超时" in str(error)
        assert "https://example.com" in str(error)
    
    def test_element_not_found_error_message(self):
        """测试元素未找到错误消息"""
        error = ElementNotFoundError("//button[@id='submit']")
        assert "//button[@id='submit']" in str(error)
    
    def test_url_validation_error_message(self):
        """测试 URL 验证错误消息"""
        error = URLValidationError("invalid-url", "格式无效")
        assert "invalid-url" in str(error)
        assert "格式无效" in str(error)
    
    def test_config_file_not_found_message(self):
        """测试配置文件未找到消息"""
        error = ConfigFileNotFoundError("/path/to/config.json")
        assert "/path/to/config.json" in str(error)
    
    def test_no_detail_links_found_message(self):
        """测试未找到详情链接消息"""
        error = NoDetailLinksFoundError("https://example.com/list")
        assert "https://example.com/list" in str(error)
    
    def test_anti_crawler_error_with_code(self):
        """测试反爬虫错误带响应码"""
        error = AntiCrawlerError("访问被拒绝", response_code=403)
        assert error.response_code == 403


class TestExceptionAttributes:
    """异常属性测试"""
    
    def test_mark_id_validation_error_without_actual(self):
        """测试 MarkIdValidationError 不带实际文本"""
        error = MarkIdValidationError(5, "期望文本")
        assert error.actual_text is None
        assert "期望" in str(error)
    
    def test_mark_id_validation_error_with_actual(self):
        """测试 MarkIdValidationError 带实际文本"""
        error = MarkIdValidationError(5, "期望", "实际")
        assert "期望" in str(error)
        assert "实际" in str(error)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
