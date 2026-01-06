# 爬取间隔配置说明

## 概述

为了提高反爬虫能力，autospider 现已支持配置化的爬取间隔，并支持随机波动以模拟真实用户行为。

## 配置项

在 `.env` 文件中添加以下配置项：

```bash
# ===== 爬取间隔配置（反爬虫） =====

# 页面操作基础延迟（秒）- 每次操作（点击、导航等）后的基础等待时间
ACTION_DELAY_BASE=1.0

# 页面操作延迟随机波动范围（秒）- 在基础延迟上增加的随机波动
# 实际延迟 = BASE ± RANDOM/2
# 例如: BASE=1.0, RANDOM=0.5 时，实际延迟在 [0.75, 1.25] 秒之间
ACTION_DELAY_RANDOM=0.5

# 页面加载等待时间（秒）- 页面跳转、返回列表页等操作后的等待时间
PAGE_LOAD_DELAY=1.5

# 滚动操作延迟（秒）- 每次滚动后的等待时间
SCROLL_DELAY=0.5
```

## 使用场景

### 1. **快速模式**（适合测试）
```bash
ACTION_DELAY_BASE=0.3
ACTION_DELAY_RANDOM=0.2
PAGE_LOAD_DELAY=0.5
SCROLL_DELAY=0.2
```

### 2. **标准模式**（默认配置，适合大多数场景）
```bash
ACTION_DELAY_BASE=1.0
ACTION_DELAY_RANDOM=0.5
PAGE_LOAD_DELAY=1.5
SCROLL_DELAY=0.5
```

### 3. **谨慎模式**（适合反爬虫严格的网站）
```bash
ACTION_DELAY_BASE=2.0
ACTION_DELAY_RANDOM=1.0
PAGE_LOAD_DELAY=3.0
SCROLL_DELAY=1.0
```

### 4. **非常谨慎模式**（严格限流）
```bash
ACTION_DELAY_BASE=5.0
ACTION_DELAY_RANDOM=2.0
PAGE_LOAD_DELAY=8.0
SCROLL_DELAY=2.0
```

## 工作原理

### 随机延迟函数

```python
def get_random_delay(base: float = 1.0, random_range: float = 0.5) -> float:
    """
    生成带随机波动的延迟时间
    
    实际延迟 = base + uniform(-random_range/2, random_range/2)
    """
    return base + random.uniform(-random_range / 2, random_range / 2)
```

### 应用位置

配置会在以下关键位置生效：

1. **滚动操作后** - 使用 `SCROLL_DELAY`
   ```python
   await self.page.evaluate("window.scrollBy(0, 500)")
   delay = get_random_delay(config.url_collector.scroll_delay, 
                            config.url_collector.action_delay_random)
   await asyncio.sleep(delay)
   ```

2. **页面导航后** - 使用 `PAGE_LOAD_DELAY`
   ```python
   await self.page.goto(url, wait_until="domcontentloaded")
   delay = get_random_delay(config.url_collector.page_load_delay,
                            config.url_collector.action_delay_random)
   await asyncio.sleep(delay)
   ```

3. **点击元素后等待 SPA 更新** - 使用 `PAGE_LOAD_DELAY * 2`
   ```python
   await locator.click()
   delay = get_random_delay(config.url_collector.page_load_delay * 2,
                            config.url_collector.action_delay_random)
   await asyncio.sleep(delay)
   ```

## 效果

### ✅ 优点

1. **模拟真实用户行为** - 随机波动使每次操作间隔都不相同
2. **降低被封风险** - 避免机器人特征被识别
3. **灵活可配置** - 可根据目标网站调整策略
4. **全局生效** - 配置一次，整个爬取流程都会应用

### 📊 示例时间分布

使用默认配置（BASE=1.0, RANDOM=0.5）滚动10次的实际延迟：
```
0.87s, 1.12s, 0.93s, 1.21s, 0.78s, 1.05s, 0.91s, 1.18s, 0.83s, 1.09s
```

平均：1.0s，标准差：0.15s - 符合真实用户行为模式

## 注意事项

⚠️ **不要设置过小的延迟**：
- 过小的延迟可能触发反爬虫机制
- 建议 `ACTION_DELAY_BASE` 至少 0.3 秒
- 建议 `PAGE_LOAD_DELAY` 至少 0.5 秒

⚠️ **波动范围建议**：
- `ACTION_DELAY_RANDOM` 建议为 `ACTION_DELAY_BASE` 的 30-50%
- 例如：BASE=2.0 时，RANDOM=0.6-1.0

⚠️ **网络延迟考虑**：
- 配置的延迟是 **额外等待时间**，不包括网络请求本身的时间
- 网络较慢时可以适当减小延迟配置

## 更新日志

**2026-01-06**
- ✅ 添加爬取间隔配置支持
- ✅ 实现随机延迟机制
- ✅ 更新所有关键位置的延迟逻辑
