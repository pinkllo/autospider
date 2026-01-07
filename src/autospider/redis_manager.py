"""Redis 管理模块，负责连接和管理 Redis 服务"""

from __future__ import annotations
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisManager:
    """Redis 连接管理器"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        db: int = 0,
        key_prefix: str = "autospider:urls",
    ):
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.key_prefix = key_prefix
        self.client: Redis | None = None
    
    async def connect(self) -> Redis | None:
        """连接到 Redis"""
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
            print(f"[Redis] 已连接到 {self.host}:{self.port}，Key 前缀: {self.key_prefix}")
            return self.client
            
        except (ConnectionRefusedError, TimeoutError, aioredis.ConnectionError) as e:
            print(f"[Redis] 连接失败: {e}")
            print(f"[Redis] 请手动启动 Redis 服务")
            
            # 连接失败，关闭客户端
            if self.client:
                await self.client.close()
                self.client = None
            
        except Exception as e:
            print(f"[Redis] 未知错误: {e}")
            if self.client:
                await self.client.close()
                self.client = None
        
        return None
    

    async def load_urls(self) -> set[str]:
        """从 Redis 加载已收集的 URL（断点续爬）"""
        if not self.client:
            return set()
        
        try:
            urls = await self.client.smembers(self.key_prefix)
            if urls:
                print(f"[Redis] 已加载 {len(urls)} 个历史 URL")
            return urls
        except Exception as e:
            print(f"[Redis] 加载 URL 失败: {e}")
            return set()
    
    async def save_url(self, url: str) -> bool:
        """保存单个 URL 到 Redis"""
        if not self.client:
            return False
        
        try:
            await self.client.sadd(self.key_prefix, url)
            return True
        except Exception as e:
            print(f"[Redis] 写入 URL 失败: {e}")
            return False
    
    async def save_urls_batch(self, urls: list[str]) -> bool:
        """批量保存 URL 到 Redis"""
        if not self.client or not urls:
            return False
        
        try:
            await self.client.sadd(self.key_prefix, *urls)
            print(f"[Redis] 批量写入 {len(urls)} 个 URL")
            return True
        except Exception as e:
            print(f"[Redis] 批量写入失败: {e}")
            return False
    
    async def get_count(self) -> int:
        """获取已存储的 URL 数量"""
        if not self.client:
            return 0
        
        try:
            return await self.client.scard(self.key_prefix)
        except Exception as e:
            print(f"[Redis] 获取计数失败: {e}")
            return 0
    
    async def close(self):
        """关闭 Redis 连接"""
        if self.client:
            await self.client.close()
            print(f"[Redis] 连接已关闭")
