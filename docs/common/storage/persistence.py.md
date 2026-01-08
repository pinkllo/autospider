# persistence.py - 持久化管理器

persistence.py 模块提供持久化管理功能，负责保存和加载配置、进度等数据。

---

## 📁 文件路径

```
src/autospider/common/storage/persistence.py
```

---

## 📑 函数目录

### 🚀 核心类
- `ConfigPersistence` - 配置持久化管理器
- `ProgressPersistence` - 进度持久化管理器

### 🔧 主要方法
- `save()` - 保存数据
- `load()` - 加载数据
- `save_progress()` - 保存进度
- `load_progress()` - 加载进度
- `append_urls()` - 追加 URL

---

## 🚀 核心功能

### ConfigPersistence

配置持久化管理器，负责保存和加载配置。

```python
from autospider.common.storage.persistence import ConfigPersistence, CollectionConfig

# 创建配置持久化管理器
config_persistence = ConfigPersistence(config_dir="output")

# 保存配置
config = CollectionConfig(
    list_url="https://example.com/list",
    task_description="收集商品详情页链接",
    nav_steps=[],
    common_detail_xpath="//a[@class='product-link']"
)
config_persistence.save(config)

# 加载配置
loaded_config = config_persistence.load()
```

### ProgressPersistence

进度持久化管理器，负责保存和加载进度。

```python
from autospider.common.storage.persistence import ProgressPersistence, CollectionProgress

# 创建进度持久化管理器
progress_persistence = ProgressPersistence(output_dir="output")

# 保存进度
progress = CollectionProgress(
    status="RUNNING",
    list_url="https://example.com/list",
    task_description="收集商品详情页链接",
    current_page_num=1,
    collected_count=10
)
progress_persistence.save_progress(progress)

# 加载进度
loaded_progress = progress_persistence.load_progress()

# 追加 URL
urls = ["https://example.com/product/1", "https://example.com/product/2"]
progress_persistence.append_urls(urls)
```

---

## 💡 特性说明

### JSON 格式

使用 JSON 格式保存和加载数据。

### 文件管理

自动管理文件路径和文件名。

---

## 🔧 使用示例

### 配置管理

```python
from autospider.common.storage.persistence import ConfigPersistence, CollectionConfig

# 创建配置持久化管理器
config_persistence = ConfigPersistence(config_dir="output")

# 保存配置
config = CollectionConfig(
    list_url="https://example.com/list",
    task_description="收集商品详情页链接",
    nav_steps=[],
    common_detail_xpath="//a[@class='product-link']",
    pagination_xpath="//a[contains(text(),'下一页')]"
)
config_persistence.save(config)

# 加载配置
loaded_config = config_persistence.load()
print(f"列表页: {loaded_config.list_url}")
print(f"任务描述: {loaded_config.task_description}")
```

### 进度管理

```python
from autospider.common.storage.persistence import ProgressPersistence, CollectionProgress

# 创建进度持久化管理器
progress_persistence = ProgressPersistence(output_dir="output")

# 保存进度
progress = CollectionProgress(
    status="RUNNING",
    list_url="https://example.com/list",
    task_description="收集商品详情页链接",
    current_page_num=5,
    collected_count=50,
    backoff_level=0,
    consecutive_success_pages=3
)
progress_persistence.save_progress(progress)

# 加载进度
loaded_progress = progress_persistence.load_progress()
print(f"当前页: {loaded_progress.current_page_num}")
print(f"已收集: {loaded_progress.collected_count}")

# 追加 URL
urls = ["https://example.com/product/1", "https://example.com/product/2"]
progress_persistence.append_urls(urls)
```

---

## 📝 最佳实践

### 配置管理

1. **定期保存**：定期保存配置避免数据丢失
2. **版本控制**：将配置文件纳入版本控制
3. **备份配置**：定期备份重要配置

### 进度管理

1. **实时保存**：每页收集后保存进度
2. **验证进度**：加载进度时验证数据完整性
3. **清理旧进度**：定期清理旧的进度文件

---

## 🔍 故障排除

### 常见问题

1. **配置保存失败**
   - 检查输出目录是否存在
   - 验证文件权限是否正确
   - 确认磁盘空间是否充足

2. **进度加载失败**
   - 检查进度文件是否存在
   - 验证文件格式是否正确
   - 确认数据结构是否匹配

---

## 📚 方法参考

### ConfigPersistence 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `save()` | config | None | 保存配置 |
| `load()` | 无 | CollectionConfig \| None | 加载配置 |

### ProgressPersistence 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `save_progress()` | progress | None | 保存进度 |
| `load_progress()` | 无 | CollectionProgress \| None | 加载进度 |
| `append_urls()` | urls | None | 追加 URL |

---

*最后更新: 2026-01-08*
