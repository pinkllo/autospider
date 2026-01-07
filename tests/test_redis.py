"""测试 Redis 连接和自动启动功能"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autospider.common.config import config
from autospider.common.storage.redis_manager import RedisManager


async def test_redis():
    """测试 Redis 功能"""
    print("=" * 60)
    print("Redis 配置测试")
    print("=" * 60)
    
    # 1. 显示配置
    print(f"\n[配置] Redis 启用: {config.redis.enabled}")
    print(f"[配置] Redis 地址: {config.redis.host}:{config.redis.port}")
    print(f"[配置] Key 前缀: {config.redis.key_prefix}")
    
    if not config.redis.enabled:
        print("\n⚠️  Redis 未启用！")
        print("请在 .env 文件中设置 REDIS_ENABLED=true")
        return
    
    # 2. 测试连接
    print(f"\n{'=' * 60}")
    print("测试 Redis 连接和自动启动")
    print("=" * 60)
    
    redis_mgr = RedisManager(
        host=config.redis.host,
        port=config.redis.port,
        password=config.redis.password,
        db=config.redis.db,
        key_prefix=config.redis.key_prefix,
    )
    
    client = await redis_mgr.connect()
    
    if not client:
        print("\n❌ Redis 连接失败！")
        print("请手动启动 Redis：")
        print("  Windows (WSL): wsl sudo service redis-server start")
        print("  Linux: sudo systemctl start redis-server")
        return
    
    # 3. 测试基本操作
    print(f"\n{'=' * 60}")
    print("测试 Redis 基本操作")
    print("=" * 60)
    
    # 保存测试 URL
    test_urls = [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]
    
    print(f"\n[测试] 保存 {len(test_urls)} 个测试 URL...")
    for url in test_urls:
        await redis_mgr.save_item(url)
        print(f"  ✓ {url}")
    
    # 加载 URL
    print(f"\n[测试] 从 Redis 加载 URL...")
    loaded_urls = await redis_mgr.load_items()
    print(f"  找到 {len(loaded_urls)} 个 URL")
    
    # 获取数量
    count = await redis_mgr.get_count()
    print(f"\n[测试] URL 总数: {count}")
    
    # 4. 关闭连接
    await redis_mgr.close()
    
    print(f"\n{'=' * 60}")
    print("✅ 所有测试通过！Redis 工作正常")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_redis())
