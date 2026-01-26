"""
全局异常处理器注册表

提供处理器的注册、获取、启用/禁用等管理功能。
所有处理器在模块加载时自动注册到此注册表，PageGuard 从这里获取处理器列表。
"""
from typing import List, Dict, Type, Optional, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from .handlers.base import BaseAnomalyHandler


class HandlerRegistry:
    """
    处理器注册表单例。
    管理所有已注册的异常处理器，支持优先级排序和启用/禁用控制。
    """
    _instance: Optional["HandlerRegistry"] = None
    
    def __new__(cls) -> "HandlerRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: Dict[str, "BaseAnomalyHandler"] = {}
            cls._instance._disabled: set = set()  # 存储被禁用的处理器名称
        return cls._instance
    
    def register(self, handler: "BaseAnomalyHandler") -> None:
        """
        注册一个处理器实例。
        
        Args:
            handler: 继承自 BaseAnomalyHandler 的处理器实例
        """
        name = handler.name
        if name in self._handlers:
            logger.warning(f"[Registry] 处理器 '{name}' 已存在，将被覆盖")
        self._handlers[name] = handler
        logger.debug(f"[Registry] 已注册处理器: {name} (priority={handler.priority})")
    
    def unregister(self, name: str) -> bool:
        """
        移除一个处理器。
        
        Args:
            name: 处理器名称
            
        Returns:
            是否成功移除
        """
        if name in self._handlers:
            del self._handlers[name]
            self._disabled.discard(name)
            logger.debug(f"[Registry] 已移除处理器: {name}")
            return True
        return False
    
    def enable(self, name: str) -> bool:
        """启用指定处理器"""
        if name in self._handlers:
            self._disabled.discard(name)
            logger.debug(f"[Registry] 已启用处理器: {name}")
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """禁用指定处理器（不移除，只是跳过检测）"""
        if name in self._handlers:
            self._disabled.add(name)
            logger.debug(f"[Registry] 已禁用处理器: {name}")
            return True
        return False
    
    def get_handlers(self) -> List["BaseAnomalyHandler"]:
        """
        获取所有已启用的处理器，按 priority 升序排列（数字越小优先级越高）。
        
        Returns:
            排序后的处理器列表
        """
        enabled_handlers = [
            h for name, h in self._handlers.items() 
            if name not in self._disabled
        ]
        # 按 priority 排序
        return sorted(enabled_handlers, key=lambda h: h.priority)
    
    def get_all_handlers(self) -> Dict[str, "BaseAnomalyHandler"]:
        """获取所有处理器（包括已禁用的），返回字典"""
        return self._handlers.copy()
    
    def is_enabled(self, name: str) -> bool:
        """检查处理器是否已启用"""
        return name in self._handlers and name not in self._disabled
    
    def clear(self) -> None:
        """清空所有处理器（主要用于测试）"""
        self._handlers.clear()
        self._disabled.clear()


# ========== 便捷函数 ==========

def get_registry() -> HandlerRegistry:
    """获取全局注册表实例"""
    return HandlerRegistry()


def register_handler(handler: "BaseAnomalyHandler") -> None:
    """注册一个处理器到全局注册表"""
    get_registry().register(handler)


def get_handlers() -> List["BaseAnomalyHandler"]:
    """获取所有已启用的处理器列表"""
    return get_registry().get_handlers()


def enable_handler(name: str) -> bool:
    """启用指定名称的处理器"""
    return get_registry().enable(name)


def disable_handler(name: str) -> bool:
    """禁用指定名称的处理器"""
    return get_registry().disable(name)


def clear_handlers() -> None:
    """清空所有处理器（主要用于测试）"""
    get_registry().clear()
