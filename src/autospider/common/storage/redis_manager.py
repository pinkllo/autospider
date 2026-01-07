"""Redis 管理模块 - 通用的 Redis 连接和数据管理工具

这是一个完全独立的 Redis 管理器，可用于任何 Python 项目。
支持逻辑删除功能，适用于需要保留删除记录的场景。
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Any
import logging

import redis.asyncio as aioredis

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisManager:
    """通用 Redis 连接管理器
    
    功能特性：
    - 异步连接管理
    - 支持逻辑删除（软删除）
    - 批量操作支持
    - 可配置的日志系统
    
    Args:
        host: Redis 服务器地址
        port: Redis 端口
        password: Redis 密码
        db: Redis 数据库索引
        key_prefix: 存储键的前缀
        logger: 可选的日志记录器，如果不提供则使用默认logger
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        db: int = 0,
        key_prefix: str = "data",
        logger: logging.Logger | None = None,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.key_prefix = key_prefix
        self.client: Redis | None = None
        self.logger = logger or logging.getLogger(__name__)
    
    async def connect(self) -> Redis | None:
        """连接到 Redis 服务器
        
        Returns:
            Redis 客户端实例，连接失败返回 None
        """
        try:
            self.client = aioredis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            
            # 测试连接
            await self.client.ping()
            self.logger.info(f"已连接到 Redis {self.host}:{self.port}，数据库: {self.db}，Key 前缀: {self.key_prefix}")
            return self.client
            
        except (ConnectionRefusedError, TimeoutError, aioredis.ConnectionError) as e:
            self.logger.error(f"Redis 连接失败: {e}")
            self.logger.info("请确保 Redis 服务正在运行")
            
            # 连接失败，关闭客户端
            if self.client:
                await self.client.close()
                self.client = None
            
        except Exception as e:
            self.logger.error(f"Redis 连接时发生未知错误: {e}")
            if self.client:
                await self.client.close()
                self.client = None
        
        return None
    

    async def load_items(self) -> set[str]:
        """从 Redis 加载所有数据项的键
        
        加载所有数据项（包括已逻辑删除的），适用于需要避免重复处理的场景。
        
        Returns:
            所有数据项键的集合
        """
        if not self.client:
            return set()
        
        try:
            # 获取所有匹配的 key
            pattern = f"{self.key_prefix}:*"
            all_keys = []
            
            async for key in self.client.scan_iter(match=pattern):
                all_keys.append(key)
            
            if not all_keys:
                return set()
            
            # 从每个 key 中提取数据项部分（移除前缀）
            items = set()
            prefix_len = len(self.key_prefix) + 1  # +1 for the colon
            
            for key in all_keys:
                item = key[prefix_len:]
                items.add(item)
            
            if items:
                self.logger.info(f"已加载 {len(items)} 个数据项（包含已删除项）")
            
            return items
            
        except Exception as e:
            self.logger.error(f"加载数据项失败: {e}")
            return set()
    
    async def save_item(self, item: str, metadata: dict[str, str] | None = None) -> bool:
        """保存单个数据项到 Redis
        
        Args:
            item: 数据项的唯一标识
            metadata: 可选的元数据字典，会自动添加 deleted=false 字段
            
        Returns:
            保存是否成功
        """
        if not self.client:
            return False
        
        try:
            key = f"{self.key_prefix}:{item}"
            
            # 构建存储的映射
            data = {"item": item, "deleted": "false"}
            if metadata:
                data.update(metadata)
            
            await self.client.hset(key, mapping=data)
            return True
        except Exception as e:
            self.logger.error(f"写入数据项失败: {e}")
            return False
    
    async def save_items_batch(self, items: list[str], metadata_list: list[dict[str, str]] | None = None) -> bool:
        """批量保存数据项到 Redis
        
        Args:
            items: 数据项标识列表
            metadata_list: 可选的元数据列表，需与 items 长度一致
            
        Returns:
            批量保存是否成功
        """
        if not self.client or not items:
            return False
        
        try:
            # 使用 pipeline 批量写入
            async with self.client.pipeline() as pipe:
                for i, item in enumerate(items):
                    key = f"{self.key_prefix}:{item}"
                    
                    data = {"item": item, "deleted": "false"}
                    if metadata_list and i < len(metadata_list):
                        data.update(metadata_list[i])
                    
                    pipe.hset(key, mapping=data)
                await pipe.execute()
            
            self.logger.info(f"批量写入 {len(items)} 个数据项")
            return True
        except Exception as e:
            self.logger.error(f"批量写入失败: {e}")
            return False
    
    async def mark_as_deleted(self, item: str) -> bool:
        """将数据项标记为逻辑删除
        
        Args:
            item: 数据项标识
            
        Returns:
            标记是否成功
        """
        if not self.client:
            return False
        
        try:
            key = f"{self.key_prefix}:{item}"
            # 检查 key 是否存在
            exists = await self.client.exists(key)
            if not exists:
                self.logger.warning(f"数据项不存在，无法标记删除: {item}")
                return False
            
            # 更新 deleted 字段
            await self.client.hset(key, "deleted", "true")
            self.logger.debug(f"已标记数据项为删除: {item}")
            return True
        except Exception as e:
            self.logger.error(f"标记删除失败: {e}")
            return False
    
    async def mark_as_deleted_batch(self, items: list[str]) -> bool:
        """批量将数据项标记为逻辑删除
        
        Args:
            items: 数据项标识列表
            
        Returns:
            批量标记是否成功
        """
        if not self.client or not items:
            return False
        
        try:
            async with self.client.pipeline() as pipe:
                for item in items:
                    key = f"{self.key_prefix}:{item}"
                    pipe.hset(key, "deleted", "true")
                await pipe.execute()
            
            self.logger.info(f"批量标记 {len(items)} 个数据项为删除")
            return True
        except Exception as e:
            self.logger.error(f"批量标记删除失败: {e}")
            return False
    
    async def is_deleted(self, item: str) -> bool:
        """检查数据项是否被逻辑删除
        
        Args:
            item: 数据项标识
            
        Returns:
            是否已删除
        """
        if not self.client:
            return False
        
        try:
            key = f"{self.key_prefix}:{item}"
            deleted = await self.client.hget(key, "deleted")
            return deleted == "true"
        except Exception as e:
            self.logger.error(f"检查删除状态失败: {e}")
            return False
    
    async def get_active_items(self) -> set[str]:
        """获取所有未被逻辑删除的数据项
        
        Returns:
            活跃数据项的集合
        """
        if not self.client:
            return set()
        
        try:
            pattern = f"{self.key_prefix}:*"
            active_items = set()
            prefix_len = len(self.key_prefix) + 1
            
            async for key in self.client.scan_iter(match=pattern):
                deleted = await self.client.hget(key, "deleted")
                if deleted != "true":
                    item = key[prefix_len:]
                    active_items.add(item)
            
            return active_items
        except Exception as e:
            self.logger.error(f"获取活跃数据项失败: {e}")
            return set()
    
    async def get_metadata(self, item: str) -> dict[str, str] | None:
        """获取数据项的元数据
        
        Args:
            item: 数据项标识
            
        Returns:
            元数据字典，如果不存在返回 None
        """
        if not self.client:
            return None
        
        try:
            key = f"{self.key_prefix}:{item}"
            data = await self.client.hgetall(key)
            return data if data else None
        except Exception as e:
            self.logger.error(f"获取元数据失败: {e}")
            return None
    
    async def get_count(self) -> int:
        """获取已存储的数据项总数（包含逻辑删除的）
        
        Returns:
            数据项总数
        """
        if not self.client:
            return 0
        
        try:
            pattern = f"{self.key_prefix}:*"
            count = 0
            async for _ in self.client.scan_iter(match=pattern):
                count += 1
            return count
        except Exception as e:
            self.logger.error(f"获取计数失败: {e}")
            return 0
    
    async def get_active_count(self) -> int:
        """获取未被逻辑删除的数据项数量
        
        Returns:
            活跃数据项数量
        """
        if not self.client:
            return 0
        
        try:
            active_items = await self.get_active_items()
            return len(active_items)
        except Exception as e:
            self.logger.error(f"获取活跃计数失败: {e}")
            return 0
    
    async def close(self):
        """关闭 Redis 连接"""
        if self.client:
            await self.client.close()
            self.logger.info("Redis 连接已关闭")
