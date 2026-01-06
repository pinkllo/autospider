# 分页爬取功能说明

## 功能概述

`autospider` 现已支持自动分页爬取功能，可以自动识别列表页的"下一页"按钮，并在多个页面间翻页收集详情页 URL。

## 实现流程

### 1. 分页控件提取（Phase 3.6）

在探索阶段完成后，系统会自动提取分页控件的 XPath：

```python
# url_collector.py 第 219-226 行
await self._extract_pagination_xpath()
```

**提取策略**：
- **常规选择器**：首先尝试使用预定义的常见分页选择器（文字、class、aria-label、title 等）
- **LLM 视觉识别**：如果常规选择器失败，则使用 LLM 视觉识别分页按钮

**支持的分页格式**：
- 文字类：`下一页`、`下页`、`>`、`>>`、`Next`
- Class 类：`next`、`pagination-next`
- 属性类：`aria-label`、`title`
- UI 框架：Ant Design、Element UI 等

### 2. 配置持久化（Phase 4.5）

提取的 `pagination_xpath` 会和其他配置一起保存到 `output/collection_config.json`：

```python
# url_collector.py 第 235-245 行
collection_config = CollectionConfig(
    nav_steps=self.nav_steps,
    common_detail_xpath=self.common_detail_xpath,
    pagination_xpath=self.pagination_xpath,  # 分页控件 xpath
    list_url=self.list_url,
    task_description=self.task_description,
)
self.config_persistence.save(collection_config)
```

### 3. 分页收集（Phase 4）

收集阶段支持两种方式，都已集成分页功能：

#### 方式 1：使用 XPath 收集（推荐）

```python
# url_collector.py 第 1151-1278 行
async def _collect_phase_with_xpath(self):
    # 外层循环：翻页
    while self.current_page_num <= max_pages:
        # 内层循环：当前页滚动收集
        while scroll_count < max_scrolls:
            # 使用 xpath 提取 URL
            ...
        
        # 翻页
        page_turned = await self._find_and_click_next_page()
        if not page_turned:
            break
```

#### 方式 2：使用 LLM 收集

```python
# url_collector.py 第 1505-1607 行
async def _collect_phase_with_llm(self):
    # 外层循环：翻页
    while self.current_page_num <= max_pages:
        # 内层循环：当前页滚动收集
        while scroll_count < max_scrolls:
            # LLM 识别详情链接
            ...
        
        # 翻页（优先使用 xpath，失败则用 LLM）
        page_turned = await self._find_and_click_next_page()
        if not page_turned:
            page_turned = await self._find_next_page_with_llm(screenshot_base64)
```

### 4. 翻页逻辑

```python
# url_collector.py 第 1280-1408 行
async def _find_and_click_next_page(self) -> bool:
    # 优先使用探索阶段提取的 pagination_xpath
    if self.pagination_xpath:
        # 使用已提取的 xpath
        ...
    
    # 如果没有或失败，尝试常见选择器
    for selector in next_page_selectors:
        # 查找并点击
        ...
    
    return page_turned
```

**智能判断**：
- 检查按钮是否禁用（`disabled`、`aria-disabled`）
- 检查按钮是否可见（`is_visible()`）
- 验证翻页是否成功
- 缓存成功的 xpath 供后续使用

## 配置参数

在 `config.py` 中可配置分页相关参数：

```python
class URLCollectorConfig(BaseModel):
    # 最大翻页次数（分页收集）
    max_pages: int = Field(
        default_factory=lambda: int(os.getenv("MAX_PAGES", "10"))
    )
    
    # 目标 URL 数量（达到后停止收集）
    target_url_count: int = Field(
        default_factory=lambda: int(os.getenv("TARGET_URL_COUNT", "5"))
    )
    
    # 最大滚动次数（单页）
    max_scrolls: int = Field(
        default_factory=lambda: int(os.getenv("MAX_SCROLLS", "20"))
    )
    
    # 连续无新 URL 的滚动次数后停止
    no_new_url_threshold: int = Field(
        default_factory=lambda: int(os.getenv("NO_NEW_URL_THRESHOLD", "3"))
    )
```

## 环境变量配置

在 `.env` 文件中设置：

```bash
# 最大翻页次数
MAX_PAGES=10

# 目标 URL 数量
TARGET_URL_COUNT=50

# 单页最大滚动次数
MAX_SCROLLS=20

# 连续无新 URL 阈值
NO_NEW_URL_THRESHOLD=3
```

## 使用示例

### 基本使用

```python
from autospider import URLCollector

# 创建收集器（会自动处理分页）
collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集招标公告详情页",
    explore_count=3,
    output_dir="output"
)

# 运行收集（自动翻页）
result = await collector.run()

print(f"共翻页 {result.current_page_num} 页")
print(f"收集到 {len(result.collected_urls)} 个 URL")
```

### 从配置恢复

如果已经有 `collection_config.json`，系统会自动加载 `pagination_xpath`：

```python
# persistence.py 会自动加载配置
config = config_persistence.load()
if config:
    pagination_xpath = config.pagination_xpath
```

## 运行日志示例

```
[Phase 3.6] 提取分页控件 xpath...
[Extract-Pagination] 滚动到页面底部查找分页控件...
[Extract-Pagination] ✓ 找到分页控件 xpath: //a[contains(text(), '下一页')]

[Phase 4] 收集阶段：使用公共 xpath 遍历列表页收集所有 URL...
[Collect-XPath] 最大翻页次数: 10

[Collect-XPath] ===== 第 1 页 =====
[Collect-XPath] 找到 20 个匹配元素
[Collect-XPath] ✓ 当前已收集 20 个 URL

[Pagination] 尝试翻页...
[Pagination] 使用已提取的 xpath: //a[contains(text(), '下一页')]
[Pagination] ✓ 翻页成功，当前第 2 页

[Collect-XPath] ===== 第 2 页 =====
...

[Collect-XPath] 收集完成!
  - 共翻页 5 页
  - 收集到 100 个 URL
```

## 注意事项

1. **分页控件检测**：
   - 系统会自动跳过禁用的按钮
   - 如果未找到分页按钮，会在当前页结束收集

2. **目标数量控制**：
   - 达到 `target_url_count` 后会停止收集
   - 可防止收集过多数据

3. **页数限制**：
   - `max_pages` 防止无限翻页
   - 建议设置合理的最大页数

4. **LLM 备用方案**：
   - 如果常规 xpath 方法失败，会使用 LLM 视觉识别
   - 增加了分页识别的鲁棒性

## 持久化配置结构

`output/collection_config.json` 示例：

```json
{
  "nav_steps": [...],
  "common_detail_xpath": "//div[@class='list']//a[@class='title']",
  "pagination_xpath": "//a[contains(text(), '下一页')]",
  "list_url": "https://example.com/list",
  "task_description": "收集招标公告详情页",
  "created_at": "2026-01-06T10:00:00",
  "updated_at": "2026-01-06T10:30:00"
}
```
