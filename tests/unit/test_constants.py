"""常量模块单元测试"""

import pytest
from autospider.common.constants import (
    # 爬取相关
    DEFAULT_SCROLL_PIXELS,
    MAX_CONSECUTIVE_BOTTOM_HITS,
    DEFAULT_RETRY_COUNT,
    DEFAULT_PAGE_TIMEOUT_MS,
    DEFAULT_ELEMENT_TIMEOUT_MS,
    # LLM 相关
    MAX_LLM_RETRIES,
    MAX_PROMPT_LENGTH,
    # URL 收集相关
    DEFAULT_EXPLORE_COUNT,
    DEFAULT_TARGET_URL_COUNT,
    DEFAULT_MAX_PAGES,
    # 存储相关
    REDIS_DEFAULT_KEY_PREFIX,
    REDIS_HASH_ID_LENGTH,
    # 输入验证
    MAX_TASK_DESCRIPTION_LENGTH,
    MAX_URL_LENGTH,
    VALID_URL_SCHEMES,
    # 文件相关
    OUTPUT_URLS_FILENAME,
    OUTPUT_COLLECTION_CONFIG,
)


class TestCrawlConstants:
    """爬取相关常量测试"""
    
    def test_scroll_pixels_is_positive(self):
        """滚动像素应为正数"""
        assert DEFAULT_SCROLL_PIXELS > 0
    
    def test_bottom_hits_is_reasonable(self):
        """连续底部命中次数应合理"""
        assert MAX_CONSECUTIVE_BOTTOM_HITS >= 1
        assert MAX_CONSECUTIVE_BOTTOM_HITS <= 10
    
    def test_retry_count_is_reasonable(self):
        """重试次数应合理"""
        assert DEFAULT_RETRY_COUNT >= 1
        assert DEFAULT_RETRY_COUNT <= 10
    
    def test_timeout_is_reasonable(self):
        """超时时间应合理"""
        assert DEFAULT_PAGE_TIMEOUT_MS >= 1000
        assert DEFAULT_ELEMENT_TIMEOUT_MS >= 1000


class TestLLMConstants:
    """LLM 相关常量测试"""
    
    def test_llm_retries_is_reasonable(self):
        """LLM 重试次数应合理"""
        assert MAX_LLM_RETRIES >= 1
        assert MAX_LLM_RETRIES <= 10
    
    def test_prompt_length_is_sufficient(self):
        """Prompt 长度应足够"""
        assert MAX_PROMPT_LENGTH >= 10000


class TestCollectionConstants:
    """URL 收集相关常量测试"""
    
    def test_explore_count_is_positive(self):
        """探索数量应为正数"""
        assert DEFAULT_EXPLORE_COUNT >= 1
    
    def test_target_count_is_positive(self):
        """目标 URL 数量应为正数"""
        assert DEFAULT_TARGET_URL_COUNT >= 1
    
    def test_max_pages_is_positive(self):
        """最大翻页数应为正数"""
        assert DEFAULT_MAX_PAGES >= 1


class TestStorageConstants:
    """存储相关常量测试"""
    
    def test_redis_prefix_not_empty(self):
        """Redis 前缀不应为空"""
        assert len(REDIS_DEFAULT_KEY_PREFIX) > 0
    
    def test_hash_length_is_reasonable(self):
        """Hash 长度应合理"""
        assert REDIS_HASH_ID_LENGTH >= 8
        assert REDIS_HASH_ID_LENGTH <= 64


class TestValidationConstants:
    """输入验证相关常量测试"""
    
    def test_task_description_length_is_reasonable(self):
        """任务描述长度限制应合理"""
        assert MAX_TASK_DESCRIPTION_LENGTH >= 100
        assert MAX_TASK_DESCRIPTION_LENGTH <= 5000
    
    def test_url_length_is_reasonable(self):
        """URL 长度限制应合理"""
        assert MAX_URL_LENGTH >= 1000
        assert MAX_URL_LENGTH <= 10000
    
    def test_valid_schemes_contains_http_https(self):
        """有效 scheme 应包含 http 和 https"""
        assert "http" in VALID_URL_SCHEMES
        assert "https" in VALID_URL_SCHEMES


class TestFileConstants:
    """文件相关常量测试"""
    
    def test_urls_filename_has_extension(self):
        """URL 文件名应有扩展名"""
        assert "." in OUTPUT_URLS_FILENAME
    
    def test_config_filename_is_json(self):
        """配置文件应为 JSON"""
        assert OUTPUT_COLLECTION_CONFIG.endswith(".json")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
