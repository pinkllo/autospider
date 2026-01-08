# models.py - 数据模型定义

models.py 模块提供 URL 收集器数据模型定义。

---

## 📁 文件路径

```
src/autospider/extractor/collector/models.py
```

---

## 📑 函数目录

### 🚀 核心类
- `DetailPageVisit` - 一次详情页访问记录
- `CommonPattern` - 从多次访问中提取的公共模式
- `URLCollectorResult` - URL 收集器结果

---

## 🚀 核心功能

### DetailPageVisit

一次详情页访问记录。

```python
from autospider.extractor.collector.models import DetailPageVisit

# 创建访问记录
visit = DetailPageVisit(
    list_page_url="https://example.com/list",
    detail_page_url="https://example.com/product/1",
    clicked_element_mark_id=5,
    clicked_element_tag="a",
    clicked_element_text="商品名称",
    clicked_element_href="/product/1",
    clicked_element_role="link",
    clicked_element_xpath_candidates=[
        {"xpath": "//a[@class='product-link']", "priority": 1, "strategy": "href"}
    ],
    step_index=1,
    timestamp="2026-01-08T10:00:00"
)
```

### CommonPattern

从多次访问中提取的公共模式。

```python
from autospider.extractor.collector.models import CommonPattern

# 创建公共模式
pattern = CommonPattern(
    tag_pattern="a",
    role_pattern="link",
    text_pattern=None,
    href_pattern=r"/product/\d+",
    common_xpath_prefix="//div[@class='product-list']",
    xpath_pattern="//a[@class='product-link']",
    confidence=0.95,
    source_visits=[visit1, visit2, visit3]
)
```

### URLCollectorResult

URL 收集器结果。

```python
from autospider.extractor.collector.models import URLCollectorResult

# 创建收集结果
result = URLCollectorResult(
    detail_visits=[visit1, visit2, visit3],
    common_pattern=pattern,
    collected_urls=["https://example.com/product/1", "https://example.com/product/2"],
    list_page_url="https://example.com/list",
    task_description="收集商品详情页链接",
    created_at="2026-01-08T10:00:00"
)
```

---

## 💡 特性说明

### 数据模型

使用 dataclass 定义数据模型：

```python
@dataclass
class DetailPageVisit:
    """一次详情页访问记录"""
    
    # 入口信息
    list_page_url: str
    detail_page_url: str
    
    # 点击的元素信息
    clicked_element_mark_id: int
    clicked_element_tag: str
    clicked_element_text: str
    clicked_element_href: str | None
    clicked_element_role: str | None
    clicked_element_xpath_candidates: list[dict]
    
    # 上下文
    step_index: int
    timestamp: str
```

---

## 🔧 使用示例

### 创建访问记录

```python
from autospider.extractor.collector.models import DetailPageVisit

# 创建访问记录
visit = DetailPageVisit(
    list_page_url="https://example.com/list",
    detail_page_url="https://example.com/product/1",
    clicked_element_mark_id=5,
    clicked_element_tag="a",
    clicked_element_text="商品名称",
    clicked_element_href="/product/1",
    clicked_element_role="link",
    clicked_element_xpath_candidates=[
        {"xpath": "//a[@class='product-link']", "priority": 1, "strategy": "href"}
    ],
    step_index=1,
    timestamp="2026-01-08T10:00:00"
)
```

### 创建收集结果

```python
from autospider.extractor.collector.models import URLCollectorResult

# 创建收集结果
result = URLCollectorResult(
    detail_visits=[visit1, visit2, visit3],
    common_pattern=pattern,
    collected_urls=["https://example.com/product/1", "https://example.com/product/2"],
    list_page_url="https://example.com/list",
    task_description="收集商品详情页链接",
    created_at="2026-01-08T10:00:00"
)

print(f"收集到 {len(result.collected_urls)} 个 URL")
```

---

## 📚 数据模型参考

### DetailPageVisit 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `list_page_url` | str | 列表页 URL |
| `detail_page_url` | str | 详情页 URL |
| `clicked_element_mark_id` | int | 点击的元素 mark_id |
| `clicked_element_tag` | str | 点击的元素标签 |
| `clicked_element_text` | str | 点击的元素文本 |
| `clicked_element_href` | str \| None | 点击的元素 href |
| `clicked_element_role` | str \| None | 点击的元素角色 |
| `clicked_element_xpath_candidates` | list[dict] | XPath 候选列表 |
| `step_index` | int | 步骤索引 |
| `timestamp` | str | 时间戳 |

### CommonPattern 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `tag_pattern` | str \| None | 标签模式 |
| `role_pattern` | str \| None | 角色模式 |
| `text_pattern` | str \| None | 文本模式（正则表达式） |
| `href_pattern` | str \| None | 链接模式（正则表达式） |
| `common_xpath_prefix` | str \| None | 公共 XPath 前缀 |
| `xpath_pattern` | str \| None | XPath 模式 |
| `confidence` | float | 置信度 |
| `source_visits` | list[DetailPageVisit] | 原始访问记录 |

### URLCollectorResult 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `detail_visits` | list[DetailPageVisit] | 详情页访问记录列表 |
| `common_pattern` | CommonPattern \| None | 公共模式 |
| `collected_urls` | list[str] | 收集的 URL 列表 |
| `list_page_url` | str | 列表页 URL |
| `task_description` | str | 任务描述 |
| `created_at` | str | 创建时间 |

---

*最后更新: 2026-01-08*
