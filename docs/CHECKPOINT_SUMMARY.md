# Checkpoint功能修复总结

## 修复内容

### 1. 配置文件修复 (`config.py`)

**新增配置项：**
- `backoff_factor`: 退避因子（默认 1.5），遭遇反爬时延迟倍增因子
- `max_backoff_level`: 最大降速等级（默认 3）
- `credit_recovery_pages`: 信用恢复阈值（默认 5），连续成功多少页后恢复一级速度

**环境变量：**
- `BACKOFF_FACTOR`
- `MAX_BACKOFF_LEVEL`
- `CREDIT_RECOVERY_PAGES`

### 2. 持久化模块扩展 (`persistence.py`)

**新增类：**

#### `CollectionProgress` 数据类
收集进度信息，包括：
- `status`: 状态（RUNNING, PAUSED, COMPLETED, FAILED）
- `pause_reason`: 暂停原因
- `current_page_num`: 当前页码
- `collected_count`: 已收集URL数量
- `backoff_level`: 降速等级
- `consecutive_success_pages`: 连续成功页数
- `last_updated`: 最后更新时间

#### `ProgressPersistence` 管理器
进度持久化管理器，提供：
- `save_progress()`: 保存进度到 `progress.json`
- `load_progress()`: 加载进度
- `append_urls()`: 追加URL到 `urls.txt`（自动去重）
- `load_collected_urls()`: 加载已收集的URL
- `has_checkpoint()`: 检查是否存在checkpoint
- `clear()`: 清除所有进度数据

### 3. URL收集器集成 (`url_collector.py`)

**新增导入：**
```python
from .persistence import ProgressPersistence, CollectionProgress
from .checkpoint import AdaptiveRateController
```

**初始化阶段：**
- 创建 `ProgressPersistence` 实例
- 创建 `AdaptiveRateController` 实例
- 打印速率控制器初始化信息

**收集阶段（XPath和LLM两种模式）：**
1. **每页开始前**：
   - 应用速率控制延迟 `await asyncio.sleep(self.rate_controller.get_delay())`
   - 可选调试输出延迟信息

2. **收集过程中**：
   - 异常捕获与处理
   - 遇到错误时应用惩罚：`self.rate_controller.apply_penalty()`
   - 成功收集URL时记录成功：`self.rate_controller.record_success()`

3. **每页结束后**：
   - 保存进度：`self._save_progress()`

**新增方法：**
```python
def _save_progress(self):
    """保存收集进度"""
    # 创建进度对象
    # 保存到文件
    # 追加新URL
```

## 工作原理

### 自适应速率控制

1. **初始状态**：使用基础延迟（default: 1.0秒）

2. **遭遇反爬**：
   - 调用 `apply_penalty()`
   - 降速等级 +1（最大为 max_backoff_level）
   - 延迟 = base_delay × (backoff_factor ^ level)
   - 例：1.0 × 1.5¹ = 1.5秒，1.0 × 1.5² = 2.25秒

3. **信用恢复**：
   - 每页成功后调用 `record_success()`
   - 累积成功计数
   - 达到阈值后自动降低一个等级
   - 延迟逐步恢复

### 断点续爬

1. **进度保存**：
   - 每页收集完成后自动保存 `progress.json`
   - URL追加到 `urls.txt`（去重）

2. **断点恢复**（未来实现）：
   - 读取 `progress.json` 获取上次状态
   - 恢复降速等级
   - 从上次页码继续收集
   - 过滤已收集的URL

## 测试验证

### 单元测试
所有测试通过 ✓：
- `TestCollectionProgress`: 进度数据类测试
- `TestProgressPersistence`: 持久化管理器测试
- `TestAdaptiveRateController`: 速率控制器测试

### 演示脚本
运行 `demo_checkpoint.py` 可以查看：
- 速率控制器的降速与恢复流程
- 进度持久化的保存与加载

运行命令：
```bash
python demo_checkpoint.py
```

## 使用示例

### 在爬虫中使用

```python
# 收集器会自动使用checkpoint功能
collector = URLCollector(
    page=page,
    list_url=list_url,
    task_description=task_description,
    output_dir="output",
)

# 运行收集（自动应用速率控制和进度保存）
result = await collector.run()
```

### 配置调整

通过环境变量或 `.env` 文件：
```bash
# 更激进的降速策略
BACKOFF_FACTOR=2.0
MAX_BACKOFF_LEVEL=5

# 更快的信用恢复
CREDIT_RECOVERY_PAGES=3
```

## 效果

✅ **自动反爬对抗**：遭遇问题时自动降速
✅ **智能恢复**：长期稳定后自动加速
✅ **断点续爬**：支持中断后继续（需要额外的恢复逻辑）
✅ **进度可见**：实时保存收集进度
✅ **配置灵活**：可通过环境变量调整策略

## 后续优化方向

1. **实现完整的断点恢复流程**：
   - 在 `run()` 方法开始时检查checkpoint
   - 使用 `ResumeCoordinator` 恢复到上次页码
   - 跳过已收集的URL

2. **更智能的反爬检测**：
   - 自动识别验证码
   - 检测IP封禁
   - 主动暂停并通知

3. **监控与报警**：
   - 实时监控降速等级
   - 等级过高时发送警告

4. **多策略切换**：
   - URL规律爆破
   - 控件直达
   - 首项检测回溯
