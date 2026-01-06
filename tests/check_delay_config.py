#!/usr/bin/env python3
"""快速检查爬取间隔配置是否生效"""

import sys
from pathlib import Path

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autospider.config import config

print("=" * 70)
print("🔍 检查爬取间隔配置")
print("=" * 70)

print("\n📋 当前配置值：")
print(f"  ACTION_DELAY_BASE      = {config.url_collector.action_delay_base} 秒")
print(f"  ACTION_DELAY_RANDOM    = {config.url_collector.action_delay_random} 秒")
print(f"  PAGE_LOAD_DELAY        = {config.url_collector.page_load_delay} 秒")
print(f"  SCROLL_DELAY           = {config.url_collector.scroll_delay} 秒")
print(f"  DEBUG_DELAY            = {config.url_collector.debug_delay}")

print("\n📊 预期延迟范围：")
base = config.url_collector.scroll_delay
random_range = config.url_collector.action_delay_random
min_delay = base - random_range / 2
max_delay = base + random_range / 2
print(f"  滚动延迟范围: [{min_delay:.2f}, {max_delay:.2f}] 秒")

base = config.url_collector.page_load_delay
min_delay = base - random_range / 2
max_delay = base + random_range / 2
print(f"  页面加载延迟范围: [{min_delay:.2f}, {max_delay:.2f}] 秒")

print("\n✅ 配置加载成功！")
print("\n💡 提示：")
print("  - 如果想看到延迟日志，运行 collect-urls 命令")
print("  - 日志中会显示 🕐 符号和具体延迟时间")
print("  - 每次延迟值都应该不同")
print("=" * 70)
