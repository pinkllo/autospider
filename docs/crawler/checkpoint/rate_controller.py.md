# rate_controller.py - 自适应速率控制器

rate_controller.py 模块实现爬虫的自适应降速与信用恢复机制。

---

## 📁 文件路径

```
src/autospider/crawler/checkpoint/rate_controller.py
```

---

## 📑 函数目录

### 🚀 核心类
- `AdaptiveRateController` - 自适应速率控制器

### 🔧 主要方法
- `get_delay()` - 获取当前延迟时间
- `get_delay_multiplier()` - 获取延迟倍率
- `apply_penalty()` - 应用惩罚（遭遇反爬时调用）
- `record_success()` - 记录成功（每页成功后调用）
- `reset()` - 重置状态
- `set_level()` - 设置降速等级（从 checkpoint 恢复时使用）

### 🔍 内部方法
- `_try_credit_recovery()` - 尝试信用恢复

---

## 🚀 核心功能

### AdaptiveRateController

自适应速率控制器，当爬虫遭遇反爬时，自动增加延迟；连续成功时逐步恢复速度。

```python
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController

# 创建速率控制器
controller = AdaptiveRateController()

# 获取当前延迟
delay = controller.get_delay()
print(f"当前延迟: {delay:.2f}秒")

# 应用惩罚（遭遇反爬时）
controller.apply_penalty()

# 记录成功（每页成功后）
controller.record_success()

# 重置状态
controller.reset()
```

### 指数退避算法

使用指数退避算法计算延迟：

```python
delay = base_delay * (backoff_factor ^ level)
```

**示例**：
- 基础延迟：1.0 秒
- 退避因子：1.5
- 降速等级 0：1.0 × 1.5^0 = 1.0 秒
- 降速等级 1：1.0 × 1.5^1 = 1.5 秒
- 降速等级 2：1.0 × 1.5^2 = 2.25 秒
- 降速等级 3：1.0 × 1.5^3 = 3.375 秒

### 信用恢复机制

连续成功一定页数后，自动恢复一个降速等级：

```python
# 连续成功 5 页后，恢复一个降速等级
credit_recovery_pages = 5

# 每页成功后记录
controller.record_success()

# 达到阈值后自动恢复
if consecutive_success_count >= credit_recovery_pages:
    current_level -= 1
```

---

## 💡 特性说明

### 自适应降速

当爬虫遭遇反爬时，自动增加延迟：

```python
def apply_penalty(self) -> None:
    """应用惩罚（遭遇反爬时调用）
    
    提升一个降速等级，重置连续成功计数
    """
    if self.current_level < self.max_level:
        self.current_level += 1
        print(f"[速率控制] ⚠ 触发惩罚，降速等级提升至 {self.current_level}/{self.max_level}")
        print(f"[速率控制] 当前延迟: {self.get_delay():.2f}秒 (基础 {self.base_delay}秒 × {self.get_delay_multiplier():.2f})")
    
    self.consecutive_success_count = 0
```

### 信用恢复

连续成功一定页数后，逐步恢复速度：

```python
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
```

### 随机延迟

使用随机延迟避免固定模式：

```python
def get_random_delay(base: float, random_range: float) -> float:
    """获取随机延迟时间
    
    Args:
        base: 基础延迟时间（秒）
        random_range: 随机浮动范围（秒）
        
    Returns:
        随机延迟时间（秒）
    """
    return base + random.uniform(0, random_range)

# 使用示例
import random
base_delay = controller.get_delay()
actual_delay = get_random_delay(base_delay, 0.5)
await asyncio.sleep(actual_delay)
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController

# 创建速率控制器
controller = AdaptiveRateController()

# 爬取循环
while True:
    # 获取当前延迟
    delay = controller.get_delay()
    print(f"等待 {delay:.2f}秒...")
    await asyncio.sleep(delay)
    
    try:
        # 执行爬取
        result = await crawl_page()
        
        # 记录成功
        controller.record_success()
        
    except Exception as e:
        # 遭遇反爬，应用惩罚
        controller.apply_penalty()
```

### 自定义配置

```python
# 自定义速率控制器
controller = AdaptiveRateController(
    base_delay=2.0,  # 基础延迟 2 秒
    backoff_factor=2.0,  # 退避因子 2.0
    max_level=5,  # 最大降速等级 5
    credit_recovery_pages=10,  # 连续成功 10 页后恢复
    initial_level=0  # 初始降速等级 0
)

# 获取当前延迟
delay = controller.get_delay()
print(f"当前延迟: {delay:.2f}秒")
```

### 断点恢复

```python
# 从 checkpoint 恢复速率控制器状态
controller = AdaptiveRateController()

# 设置降速等级（从 checkpoint 恢复时使用）
controller.set_level(2)

# 恢复连续成功计数
controller.consecutive_success_count = 3

print(f"当前降速等级: {controller.current_level}")
print(f"连续成功页数: {controller.consecutive_success_count}")
print(f"当前延迟: {controller.get_delay():.2f}秒")
```

### 随机延迟

```python
from autospider.crawler.checkpoint.rate_controller import get_random_delay

# 获取随机延迟
base_delay = controller.get_delay()
random_range = 0.5
actual_delay = get_random_delay(base_delay, random_range)

print(f"基础延迟: {base_delay:.2f}秒")
print(f"随机延迟: {actual_delay:.2f}秒")

await asyncio.sleep(actual_delay)
```

---

## 📝 最佳实践

### 速率控制

1. **合理设置基础延迟**：根据网站响应时间设置合理的基础延迟
2. **选择合适的退避因子**：通常 1.5-2.0 之间
3. **设置最大降速等级**：避免延迟过大导致超时

### 信用恢复

1. **设置合理的恢复阈值**：通常 5-10 页
2. **避免频繁降速**：只有在确实遭遇反爬时才应用惩罚
3. **监控降速状态**：定期检查降速等级

### 随机延迟

1. **使用随机延迟**：避免固定模式被识别
2. **设置合理的随机范围**：通常为基础延迟的 50%
3. **结合速率控制**：在基础延迟上添加随机浮动

### 断点恢复

1. **保存速率状态**：将降速等级和连续成功计数保存到 checkpoint
2. **恢复速率状态**：从 checkpoint 恢复速率控制器状态
3. **验证恢复结果**：确认恢复后的延迟是否合理

---

## 🔍 故障排除

### 常见问题

1. **延迟过大**
   - 检查降速等级是否过高
   - 验证基础延迟设置是否合理
   - 确认退避因子是否过大

2. **频繁降速**
   - 检查是否真的遭遇反爬
   - 验证异常处理逻辑是否正确
   - 确认是否误判正常失败为反爬

3. **无法恢复速度**
   - 检查连续成功计数是否正确累积
   - 验证恢复阈值是否设置过高
   - 确认信用恢复逻辑是否正常

4. **随机延迟不生效**
   - 检查是否正确调用 `get_random_delay()`
   - 验证随机范围设置是否合理
   - 确认是否正确使用随机延迟

### 调试技巧

```python
# 检查速率控制器状态
print(f"当前降速等级: {controller.current_level}")
print(f"连续成功页数: {controller.consecutive_success_count}")
print(f"基础延迟: {controller.base_delay}秒")
print(f"退避因子: {controller.backoff_factor}")
print(f"最大降速等级: {controller.max_level}")
print(f"恢复阈值: {controller.credit_recovery_pages}")
print(f"当前延迟: {controller.get_delay():.2f}秒")
print(f"延迟倍率: {controller.get_delay_multiplier():.2f}")
print(f"是否降速: {controller.is_slowed}")

# 模拟降速和恢复
controller.apply_penalty()
print(f"应用惩罚后延迟: {controller.get_delay():.2f}秒")

for i in range(10):
    controller.record_success()
    print(f"第 {i+1} 次成功后延迟: {controller.get_delay():.2f}秒")
```

---

## 📚 方法参考

### AdaptiveRateController 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `get_delay()` | 无 | float | 获取当前延迟时间（秒） |
| `get_delay_multiplier()` | 无 | float | 获取延迟倍率 |
| `apply_penalty()` | 无 | None | 应用惩罚（遭遇反爬时调用） |
| `record_success()` | 无 | None | 记录成功（每页成功后调用） |
| `reset()` | 无 | None | 重置状态 |
| `set_level()` | level | None | 设置降速等级（从 checkpoint 恢复时使用） |

### 便捷函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `get_random_delay()` | base, random_range | float | 获取随机延迟时间（秒） |

---

## 📊 配置参数

### AdaptiveRateController 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_delay` | float | 从配置读取 | 基础延迟时间（秒） |
| `backoff_factor` | float | 从配置读取 | 退避因子 |
| `max_level` | int | 从配置读取 | 最大降速等级 |
| `credit_recovery_pages` | int | 从配置读取 | 连续成功多少页后恢复一级 |
| `initial_level` | int | 0 | 初始降速等级 |

### 配置文件示例

```python
# config.py
class URLCollectorConfig(BaseModel):
    action_delay_base: float = 1.0  # 基础延迟
    action_delay_random: float = 0.5  # 随机浮动范围
    backoff_factor: float = 1.5  # 退避因子
    max_backoff_level: int = 3  # 最大降速等级
    credit_recovery_pages: int = 5  # 恢复阈值
```

---

*最后更新: 2026-01-08*
