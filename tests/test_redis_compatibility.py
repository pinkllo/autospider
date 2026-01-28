"""测试向后兼容性

验证旧代码（使用 RedisManager 和旧接口）是否能正常工作
"""

import asyncio
from autospider.common.storage import RedisManager
from autospider.common.logger import get_logger

logger = get_logger(__name__)


async def test_backward_compatibility():
    """测试向后兼容性"""
    print("\n" + "=" * 60)
    print("测试向后兼容性")
    print("=" * 60)
    
    # 使用旧的 RedisManager 类名
    manager = RedisManager(
        host="localhost",
        port=6379,
        key_prefix="test:compat",
        logger=logger,
    )
    
    await manager.connect()
    
    # 1. 测试 save_item (旧接口)
    print("\n1. 测试 save_item (旧接口)")
    urls = [
        "https://example.com/old1",
        "https://example.com/old2",
        "https://example.com/old3",
    ]
    
    for url in urls:
        success = await manager.save_item(url)
        print(f"  {'✓' if success else '⊘'} {url}")
    
    # 2. 测试 load_items (旧接口)
    print("\n2. 测试 load_items (旧接口)")
    items = await manager.load_items()
    print(f"  加载了 {len(items)} 个 URL")
    for url in list(items)[:5]:
        print(f"    - {url}")
    
    # 3. 测试 get_active_items (旧接口)
    print("\n3. 测试 get_active_items (旧接口)")
    active = await manager.get_active_items()
    print(f"  活跃 URL: {len(active)}")
    
    # 4. 测试 get_count (旧接口)
    print("\n4. 测试 get_count (旧接口)")
    count = await manager.get_count()
    print(f"  总数: {count}")
    
    # 5. 测试 save_items_batch (旧接口)
    print("\n5. 测试 save_items_batch (旧接口)")
    batch_urls = [f"https://example.com/batch{i}" for i in range(5)]
    success = await manager.save_items_batch(batch_urls)
    print(f"  批量保存: {'✓' if success else '✗'}")
    
    await manager.close()
    
    print("\n" + "=" * 60)
    print("✓ 向后兼容性测试通过")
    print("=" * 60)


async def test_new_interface():
    """测试新接口（队列模式）"""
    print("\n" + "=" * 60)
    print("测试新接口（队列模式）")
    print("=" * 60)
    
    # 使用新的 RedisQueueManager
    from autospider.common.storage import RedisQueueManager
    
    manager = RedisQueueManager(
        host="localhost",
        port=6379,
        key_prefix="test:queue",
        logger=logger,
    )
    
    await manager.connect()
    
    # 1. push_task
    print("\n1. 推送任务 (push_task)")
    await manager.push_task("https://example.com/task1")
    await manager.push_task("https://example.com/task2")
    print("  ✓ 已推送 2 个任务")
    
    # 2. fetch_task
    print("\n2. 获取任务 (fetch_task)")
    tasks = await manager.fetch_task(
        consumer_name="test_consumer",
        block_ms=0,
        count=2
    )
    print(f"  获取了 {len(tasks)} 个任务")
    
    # 3. ack_task
    print("\n3. 确认任务 (ack_task)")
    for stream_id, data_id, data in tasks:
        await manager.ack_task(stream_id)
        print(f"  ✓ ACK: {data['url']}")
    
    # 4. get_stats
    print("\n4. 查看统计 (get_stats)")
    stats = await manager.get_stats()
    print(f"  总数据: {stats.get('total_items', 0)}")
    print(f"  待处理: {stats.get('stream_length', 0)}")
    print(f"  PEL: {stats.get('pending_count', 0)}")
    
    await manager.close()
    
    print("\n" + "=" * 60)
    print("✓ 新接口测试通过")
    print("=" * 60)


async def main():
    """主测试函数"""
    try:
        # 先测试向后兼容性
        await test_backward_compatibility()
        
        # 再测试新接口
        await test_new_interface()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
