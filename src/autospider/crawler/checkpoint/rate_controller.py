"""自适应速率控制器

实现爬虫的自适应降速与信用恢复机制
"""

from __future__ import annotations

from ...common.config import config
from ...common.utils.delay import get_random_delay


class AdaptiveRateController:
    """自适应速率控制器
    
    当爬虫遭遇反爬时，自动增加延迟；连续成功时逐步恢复速度。
    
    使用指数退避算法：delay = base_delay * (backoff_factor ^ level)
    """
    
    def __init__(
        self,
        base_delay: float | None = None,
        backoff_factor: float | None = None,
        max_level: int | None = None,
        credit_recovery_pages: int | None = None,
        initial_level: int = 0,
    ):
        """初始化
        
        Args:
            base_delay: 基础延迟时间（秒），默认从配置读取
            backoff_factor: 退避因子，默认从配置读取
            max_level: 最大降速等级，默认从配置读取
            credit_recovery_pages: 连续成功多少页后恢复一级，默认从配置读取
            initial_level: 初始降速等级
        """
        self.base_delay = base_delay or config.url_collector.action_delay_base
        self.backoff_factor = backoff_factor or config.url_collector.backoff_factor
        self.max_level = max_level or config.url_collector.max_backoff_level
        self.credit_recovery_pages = credit_recovery_pages or config.url_collector.credit_recovery_pages
        
        self.current_level = initial_level
        self.consecutive_success_count = 0
    
    def get_delay(self) -> float:
        """获取当前延迟时间
        
        Returns:
            延迟时间（秒）
        """
        delay = self.base_delay * (self.backoff_factor ** self.current_level)
        return delay
    
    def get_delay_multiplier(self) -> float:
        """获取延迟倍率（用于其他延迟配置）
        
        Returns:
            延迟倍率
        """
        return self.backoff_factor ** self.current_level
    
    def apply_penalty(self) -> None:
        """应用惩罚（遭遇反爬时调用）
        
        提升一个降速等级，重置连续成功计数
        """
        if self.current_level < self.max_level:
            self.current_level += 1
            print(f"[速率控制] ⚠ 触发惩罚，降速等级提升至 {self.current_level}/{self.max_level}")
            print(f"[速率控制] 当前延迟: {self.get_delay():.2f}秒 (基础 {self.base_delay}秒 × {self.get_delay_multiplier():.2f})")
        else:
            print(f"[速率控制] ⚠ 已达最大降速等级 {self.max_level}")
        
        self.consecutive_success_count = 0
    
    def record_success(self) -> None:
        """记录成功（每页成功后调用）
        
        累积成功计数，达到阈值后尝试恢复
        """
        self.consecutive_success_count += 1
        
        if self.consecutive_success_count >= self.credit_recovery_pages:
            self._try_credit_recovery()
    
    def _try_credit_recovery(self) -> None:
        """尝试信用恢复"""
        if self.current_level > 0:
            self.current_level -= 1
            print(f"[速率控制] ✓ 信用恢复，降速等级降至 {self.current_level}/{self.max_level}")
            print(f"[速率控制] 当前延迟: {self.get_delay():.2f}秒")
        
        self.consecutive_success_count = 0
    
    def reset(self) -> None:
        """重置状态"""
        self.current_level = 0
        self.consecutive_success_count = 0
        print("[速率控制] 状态已重置")
    
    def set_level(self, level: int) -> None:
        """设置降速等级（从 checkpoint 恢复时使用）
        
        Args:
            level: 降速等级
        """
        self.current_level = min(level, self.max_level)
        if self.current_level > 0:
            print(f"[速率控制] 从检查点恢复，当前降速等级: {self.current_level}")
            print(f"[速率控制] 当前延迟: {self.get_delay():.2f}秒")
    
    @property
    def is_slowed(self) -> bool:
        """是否处于降速状态"""
        return self.current_level > 0
