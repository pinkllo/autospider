"""验证工具单元测试"""

import pytest
from autospider.common.validators import (
    validate_url,
    validate_task_description,
    validate_positive_integer,
    sanitize_filename,
)
from autospider.common.exceptions import URLValidationError, ValidationError


class TestValidateUrl:
    """URL 验证测试"""
    
    def test_valid_https_url(self):
        """测试有效的 HTTPS URL"""
        url = validate_url("https://example.com/path")
        assert url == "https://example.com/path"
    
    def test_valid_http_url(self):
        """测试有效的 HTTP URL"""
        url = validate_url("http://example.com")
        assert url == "http://example.com"
    
    def test_url_with_whitespace(self):
        """测试 URL 前后有空白"""
        url = validate_url("  https://example.com  ")
        assert url == "https://example.com"
    
    def test_empty_url_raises_error(self):
        """测试空 URL 抛出异常"""
        with pytest.raises(URLValidationError) as exc_info:
            validate_url("")
        assert "URL 不能为空" in str(exc_info.value)
    
    def test_empty_url_allowed(self):
        """测试允许空 URL"""
        url = validate_url("", allow_empty=True)
        assert url == ""
    
    def test_missing_scheme_raises_error(self):
        """测试缺少协议抛出异常"""
        with pytest.raises(URLValidationError) as exc_info:
            validate_url("example.com/path")
        assert "缺少协议" in str(exc_info.value)
    
    def test_invalid_scheme_raises_error(self):
        """测试无效协议抛出异常"""
        with pytest.raises(URLValidationError) as exc_info:
            validate_url("ftp://example.com")
        assert "不支持的协议" in str(exc_info.value)
    
    def test_missing_domain_raises_error(self):
        """测试缺少域名抛出异常"""
        with pytest.raises(URLValidationError) as exc_info:
            validate_url("https:///path")
        assert "缺少域名" in str(exc_info.value)
    
    def test_url_too_long_raises_error(self):
        """测试 URL 过长抛出异常"""
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(URLValidationError) as exc_info:
            validate_url(long_url)
        assert "长度超过" in str(exc_info.value)


class TestValidateTaskDescription:
    """任务描述验证测试"""
    
    def test_valid_description(self):
        """测试有效的任务描述"""
        task = validate_task_description("收集招标公告详情页")
        assert task == "收集招标公告详情页"
    
    def test_description_with_whitespace(self):
        """测试描述前后有空白"""
        task = validate_task_description("  收集招标公告  ")
        assert task == "收集招标公告"
    
    def test_empty_description_raises_error(self):
        """测试空描述抛出异常"""
        with pytest.raises(ValidationError) as exc_info:
            validate_task_description("")
        assert "不能为空" in str(exc_info.value)
    
    def test_whitespace_only_description_raises_error(self):
        """测试只有空白的描述抛出异常"""
        with pytest.raises(ValidationError) as exc_info:
            validate_task_description("   ")
        assert "不能为空" in str(exc_info.value)
    
    def test_description_too_long_raises_error(self):
        """测试描述过长抛出异常"""
        long_task = "a" * 600
        with pytest.raises(ValidationError) as exc_info:
            validate_task_description(long_task)
        assert "不能超过" in str(exc_info.value)
    
    def test_dangerous_content_raises_error(self):
        """测试危险内容抛出异常"""
        with pytest.raises(ValidationError) as exc_info:
            validate_task_description("test <script>alert(1)</script>")
        assert "不允许的内容" in str(exc_info.value)


class TestValidatePositiveInteger:
    """正整数验证测试"""
    
    def test_valid_integer(self):
        """测试有效的正整数"""
        value = validate_positive_integer(5, "count")
        assert value == 5
    
    def test_minimum_value(self):
        """测试最小值"""
        value = validate_positive_integer(1, "count")
        assert value == 1
    
    def test_below_minimum_raises_error(self):
        """测试低于最小值抛出异常"""
        with pytest.raises(ValidationError) as exc_info:
            validate_positive_integer(0, "count")
        assert "至少为" in str(exc_info.value)
    
    def test_above_maximum_raises_error(self):
        """测试超过最大值抛出异常"""
        with pytest.raises(ValidationError) as exc_info:
            validate_positive_integer(100, "count", max_value=50)
        assert "不能超过" in str(exc_info.value)


class TestSanitizeFilename:
    """文件名清理测试"""
    
    def test_normal_filename(self):
        """测试正常文件名"""
        name = sanitize_filename("report.txt")
        assert name == "report.txt"
    
    def test_filename_with_unsafe_chars(self):
        """测试包含不安全字符的文件名"""
        name = sanitize_filename("file/name:with*chars")
        assert "/" not in name
        assert ":" not in name
        assert "*" not in name
    
    def test_filename_with_leading_dots(self):
        """测试首尾有点的文件名"""
        name = sanitize_filename("...hidden...")
        assert not name.startswith(".")
        assert not name.endswith(".")
    
    def test_empty_filename_returns_unnamed(self):
        """测试空文件名返回 unnamed"""
        name = sanitize_filename("")
        assert name == "unnamed"
    
    def test_long_filename_truncated(self):
        """测试过长文件名被截断"""
        long_name = "a" * 300
        name = sanitize_filename(long_name)
        assert len(name) <= 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
