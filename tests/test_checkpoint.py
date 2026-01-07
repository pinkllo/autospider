"""断点续爬模块单元测试"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autospider.common.storage.persistence import CollectionProgress, ProgressPersistence
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController


class TestCollectionProgress:
    """CollectionProgress 数据类测试"""
    
    def test_default_values(self):
        """测试默认值"""
        progress = CollectionProgress()
        assert progress.status == "RUNNING"
        assert progress.pause_reason is None
        assert progress.current_page_num == 1
        assert progress.collected_count == 0
        assert progress.backoff_level == 0
        assert progress.consecutive_success_pages == 0
    
    def test_to_dict(self):
        """测试序列化为字典"""
        progress = CollectionProgress(
            status="PAUSED",
            pause_reason="ANTI_BOT",
            current_page_num=50,
            collected_count=1000,
            backoff_level=2,
        )
        
        data = progress.to_dict()
        
        assert data["status"] == "PAUSED"
        assert data["pause_reason"] == "ANTI_BOT"
        assert data["current_page_num"] == 50
        assert data["collected_count"] == 1000
        assert data["backoff_level"] == 2
    
    def test_from_dict(self):
        """测试从字典反序列化"""
        data = {
            "status": "COMPLETED",
            "current_page_num": 100,
            "collected_count": 5000,
            "backoff_level": 1,
        }
        
        progress = CollectionProgress.from_dict(data)
        
        assert progress.status == "COMPLETED"
        assert progress.current_page_num == 100
        assert progress.collected_count == 5000
        assert progress.backoff_level == 1


class TestProgressPersistence:
    """ProgressPersistence 管理器测试"""
    
    def test_save_and_load_progress(self):
        """测试保存和加载进度"""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ProgressPersistence(tmpdir)
            
            # 保存
            progress = CollectionProgress(
                status="RUNNING",
                current_page_num=25,
                collected_count=500,
            )
            persistence.save_progress(progress)
            
            # 加载
            loaded = persistence.load_progress()
            
            assert loaded is not None
            assert loaded.status == "RUNNING"
            assert loaded.current_page_num == 25
            assert loaded.collected_count == 500
            assert loaded.last_updated != ""  # 应该有时间戳
    
    def test_append_and_load_urls(self):
        """测试 URL 追加和加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ProgressPersistence(tmpdir)
            
            # 追加 URL
            urls1 = ["http://example.com/1", "http://example.com/2"]
            persistence.append_urls(urls1)
            
            urls2 = ["http://example.com/3"]
            persistence.append_urls(urls2)
            
            # 加载
            collected = persistence.load_collected_urls()
            
            assert len(collected) == 3
            assert "http://example.com/1" in collected
            assert "http://example.com/2" in collected
            assert "http://example.com/3" in collected
    
    def test_clear(self):
        """测试清除进度"""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ProgressPersistence(tmpdir)
            
            # 保存一些数据
            persistence.save_progress(CollectionProgress())
            persistence.append_urls(["http://example.com"])
            
            # 清除
            persistence.clear()
            
            # 验证已清除
            assert not persistence.has_checkpoint()
            assert len(persistence.load_collected_urls()) == 0


class TestAdaptiveRateController:
    """AdaptiveRateController 测试"""
    
    def test_default_delay(self):
        """测试默认延迟"""
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )
        
        # Level 0: 延迟 = 1.0 * 1.5^0 = 1.0
        assert controller.get_delay() == 1.0
        assert controller.current_level == 0
    
    def test_apply_penalty(self):
        """测试惩罚机制"""
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )
        
        controller.apply_penalty()
        
        # Level 1: 延迟 = 1.0 * 1.5^1 = 1.5
        assert controller.current_level == 1
        assert controller.get_delay() == 1.5
        
        controller.apply_penalty()
        
        # Level 2: 延迟 = 1.0 * 1.5^2 = 2.25
        assert controller.current_level == 2
        assert controller.get_delay() == 2.25
    
    def test_max_penalty_level(self):
        """测试最大惩罚等级限制"""
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=2.0,
            max_level=2,
            credit_recovery_pages=5,
        )
        
        controller.apply_penalty()
        controller.apply_penalty()
        controller.apply_penalty()  # 超过最大等级
        
        assert controller.current_level == 2  # 不超过最大值
    
    def test_credit_recovery(self):
        """测试信用恢复"""
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=3,  # 连续成功 3 页后恢复
        )
        
        # 先加一级惩罚
        controller.apply_penalty()
        assert controller.current_level == 1
        
        # 记录成功
        controller.record_success()
        controller.record_success()
        controller.record_success()  # 第 3 次触发恢复
        
        assert controller.current_level == 0
    
    def test_set_level(self):
        """测试设置等级（从 checkpoint 恢复）"""
        controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=3,
            credit_recovery_pages=5,
        )
        
        controller.set_level(2)
        
        assert controller.current_level == 2
        assert controller.get_delay() == 2.25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
