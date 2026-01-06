#!/usr/bin/env python3
"""测试随机延迟功能"""

import sys
from pathlib import Path

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autospider.config import config
from autospider.url_collector import get_random_delay


def test_random_delay():
    """测试随机延迟生成"""
    print("=" * 60)
    print("测试随机延迟功能")
    print("=" * 60)
    
    # 显示当前配置
    print(f"\n当前配置：")
    print(f"  ACTION_DELAY_BASE: {config.url_collector.action_delay_base}s")
    print(f"  ACTION_DELAY_RANDOM: {config.url_collector.action_delay_random}s")
    print(f"  PAGE_LOAD_DELAY: {config.url_collector.page_load_delay}s")
    print(f"  SCROLL_DELAY: {config.url_collector.scroll_delay}s")
    
    # 测试滚动延迟
    print(f"\n测试滚动延迟（10次）：")
    delays = []
    for i in range(10):
        delay = get_random_delay(
            config.url_collector.scroll_delay,
            config.url_collector.action_delay_random
        )
        delays.append(delay)
        print(f"  第 {i+1} 次: {delay:.3f}s")
    
    avg = sum(delays) / len(delays)
    min_val = min(delays)
    max_val = max(delays)
    
    print(f"\n统计信息：")
    print(f"  平均值: {avg:.3f}s")
    print(f"  最小值: {min_val:.3f}s")
    print(f"  最大值: {max_val:.3f}s")
    print(f"  范围: [{min_val:.3f}, {max_val:.3f}]s")
    
    # 测试页面加载延迟
    print(f"\n测试页面加载延迟（5次）：")
    delays = []
    for i in range(5):
        delay = get_random_delay(
            config.url_collector.page_load_delay,
            config.url_collector.action_delay_random
        )
        delays.append(delay)
        print(f"  第 {i+1} 次: {delay:.3f}s")
    
    avg = sum(delays) / len(delays)
    print(f"  平均值: {avg:.3f}s")
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_random_delay()
