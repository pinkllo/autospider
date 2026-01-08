# navigation_handler.py - 导航处理器

navigation_handler.py 模块提供导航处理功能，负责导航阶段的筛选操作和步骤重放。

---

## 📁 文件路径

```
src/autospider/extractor/collector/navigation_handler.py
```

---

## 📑 函数目录

### 🚀 核心类
- `NavigationHandler` - 导航处理器主类

### 🔧 主要方法
- `run_navigation_phase()` - 导航阶段：让 LLM 根据任务描述进行筛选操作
- `replay_nav_steps()` - 重放已保存的导航步骤

---

## 🚀 核心功能

### NavigationHandler

导航处理器，负责导航阶段的筛选操作和步骤重放。

```python
from autospider.extractor.collector.navigation_handler import NavigationHandler

# 创建导航处理器
handler = NavigationHandler(
    page=page,
    list_url="https://example.com/list",
    task_description="筛选价格低于100的商品",
    max_nav_steps=10,
    decider=decider,
    screenshots_dir=screenshots_dir
)

# 运行导航阶段
success = await handler.run_navigation_phase()

if success:
    print("导航阶段完成")
    print(f"导航步骤: {len(handler.nav_steps)}")
```

### 导航阶段

让 LLM 根据任务描述进行筛选操作：

```python
# 运行导航阶段
success = await handler.run_navigation_phase()

# 保存导航步骤
nav_steps = handler.nav_steps
```

### 步骤重放

重放已保存的导航步骤：

```python
# 重放导航步骤
success = await handler.replay_nav_steps(nav_steps)

if success:
    print("导航步骤重放成功")
```

---

## 💡 特性说明

### LLM 驱动的导航

使用 LLM 根据任务描述进行筛选操作：

```python
# 让 LLM 根据任务描述进行筛选操作
nav_success = await navigation_handler.run_navigation_phase()
```

### 步骤沉淀

自动沉淀导航步骤以便重放：

```python
# 保存导航步骤
nav_steps = navigation_handler.nav_steps

# 重放导航步骤
await navigation_handler.replay_nav_steps(nav_steps)
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.collector.navigation_handler import NavigationHandler

# 创建导航处理器
handler = NavigationHandler(
    page=page,
    list_url="https://example.com/list",
    task_description="筛选价格低于100的商品",
    max_nav_steps=10,
    decider=decider,
    screenshots_dir="output/screenshots"
)

# 运行导航阶段
success = await handler.run_navigation_phase()

if success:
    print("导航阶段完成")
    print(f"导航步骤: {len(handler.nav_steps)}")
```

### 步骤重放

```python
# 重放导航步骤
success = await handler.replay_nav_steps(nav_steps)

if success:
    print("导航步骤重放成功")
else:
    print("导航步骤重放失败")
```

---

## 📝 最佳实践

### 导航设计

1. **清晰的任务描述**：提供清晰、具体的任务描述
2. **合理的步骤限制**：设置合理的最大导航步骤数
3. **保存导航步骤**：保存导航步骤以便重放

### 步骤重放

1. **验证步骤有效性**：重放前验证步骤是否有效
2. **处理重放失败**：妥善处理重放失败的情况
3. **记录重放日志**：详细记录重放过程便于调试

---

## 🔍 故障排除

### 常见问题

1. **导航阶段失败**
   - 检查任务描述是否清晰
   - 验证页面加载完成
   - 确认 LLM 决策是否正确

2. **步骤重放失败**
   - 检查导航步骤是否正确
   - 验证元素选择器是否有效
   - 确认页面状态是否正确

---

## 📚 方法参考

### NavigationHandler 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run_navigation_phase()` | 无 | bool | 导航阶段：让 LLM 根据任务描述进行筛选操作 |
| `replay_nav_steps()` | nav_steps | bool | 重放已保存的导航步骤 |

---

*最后更新: 2026-01-08*
