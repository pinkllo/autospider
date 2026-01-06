# 分页爬取功能实现总结

## 概述

已成功为 AutoSpider 增加**自动分页爬取功能**，系统现在可以：
- ✅ 自动识别"下一页"按钮
- ✅ 提取分页控件的 XPath
- ✅ 在收集阶段自动翻页
- ✅ 持久化分页配置
- ✅ 支持多种分页格式

## 已完成的改动

### 1. 持久化模块 (`persistence.py`)

**修改**: 已在 `CollectionConfig` 中添加 `pagination_xpath` 字段

```python
@dataclass
class CollectionConfig:
    nav_steps: list[dict[str, Any]] = field(default_factory=list)
    common_detail_xpath: str | None = None
    pagination_xpath: str | None = None  # ✅ 已添加
    list_url: str = ""
    task_description: str = ""
    created_at: str = ""
    updated_at: str = ""
```

### 2. URL 收集器 (`url_collector.py`)

**已实现的功能**：

#### Phase 3.6: 提取分页控件 XPath (第 979-1149 行)
```python
async def _extract_pagination_xpath(self) -> None:
    # 1. 常规选择器匹配
    # 2. LLM 视觉识别 (备用)
```

支持的分页格式：
- 文字类: `下一页`, `下页`, `>`, `>>`, `Next`
- Class类: `next`, `pagination-next`
- 属性类: `aria-label`, `title`
- UI框架: Ant Design, Element UI

#### 收集阶段分页支持 (第 1151-1607 行)

两种收集方式都已支持分页：

**方式 1: XPath 收集** (`_collect_phase_with_xpath`)
```python
while current_page_num <= max_pages:
    # 当前页滚动收集
    while scroll_count < max_scrolls:
        # 收集 URL
        ...
    
    # 翻页
    page_turned = await self._find_and_click_next_page()
    if not page_turned:
        break
```

**方式 2: LLM 收集** (`_collect_phase_with_llm`)
- 同样支持分页
- 备用 LLM 视觉识别翻页按钮

#### 翻页逻辑 (第 1280-1467 行)

```python
async def _find_and_click_next_page(self) -> bool:
    # 优先使用已提取的 pagination_xpath
    if self.pagination_xpath:
        # 使用已提取的 xpath
        ...
    
    # 尝试常见选择器
    for selector in next_page_selectors:
        # 查找并点击
        ...
    
    return page_turned

async def _find_next_page_with_llm(self, screenshot_base64: str) -> bool:
    # LLM 视觉识别翻页按钮 (备用)
    ...
```

**智能判断**:
- ✅ 检查按钮是否禁用
- ✅ 检查按钮是否可见
- ✅ 验证翻页是否成功
- ✅ 缓存成功的 xpath

#### 配置持久化 (第 235-245 行)

在 `run()` 方法中保存配置：
```python
collection_config = CollectionConfig(
    nav_steps=self.nav_steps,
    common_detail_xpath=self.common_detail_xpath,
    pagination_xpath=self.pagination_xpath,  # ✅
    list_url=self.list_url,
    task_description=self.task_description,
)
self.config_persistence.save(collection_config)
```

### 3. 配置管理 (`config.py`)

**已添加配置参数**:

```python
class URLCollectorConfig(BaseModel):
    # 最大翻页次数
    max_pages: int = Field(
        default_factory=lambda: int(os.getenv("MAX_PAGES", "10"))
    )
```

环境变量:
```bash
MAX_PAGES=10  # 最大翻页次数
```

### 4. 文档

**已创建**:
1. **`docs/pagination_feature.md`** - 分页功能详细说明
   - 实现流程
   - 配置参数
   - 使用示例
   - 运行日志

2. **`docs/workflow_overview.md`** - 完整工作流程概览
   - 两阶段架构说明
   - 分页功能集成
   - 配置参数详解

3. **`README.md`** - 更新
   - 核心特性中添加分页功能
   - 工作流程中添加分页阶段
   - 输出文件中添加配置文件说明

## 工作流程

```
Phase 1: 导航到列表页
    ↓
Phase 2: 导航阶段 (筛选操作)
    ↓
Phase 3: 探索阶段 (进入详情页)
    ↓
Phase 3.5: 提取公共 XPath
    ↓
Phase 3.6: 提取分页控件 XPath ⭐ 新增
    ↓
Phase 4: 收集阶段 (自动翻页) ⭐ 增强
    ↓
Phase 4.5: 持久化配置 ⭐ 新增
    ↓
Phase 5: 生成爬虫脚本
```

## 输出文件

收集完成后会生成：

```
output/
├── urls.txt                    # URL 列表
├── collection_config.json      # 配置文件 ⭐ (包含 pagination_xpath)
├── collected_urls.json         # 完整收集结果
├── spider.py                   # 生成的爬虫脚本
└── screenshots/                # 截图

screenshots/
├── explore_1.png
├── explore_2.png
├── pagination_extract.png      # 分页提取截图 ⭐
└── collect_*.png
```

`collection_config.json` 示例:
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

## 运行示例

```bash
# 运行 URL 收集器（会自动分页）
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页"

# 输出日志示例：
# [Phase 3.6] 提取分页控件 xpath...
# [Extract-Pagination] ✓ 找到分页控件 xpath: //a[contains(text(), '下一页')]
# 
# [Collect-XPath] ===== 第 1 页 =====
# [Collect-XPath] ✓ 当前已收集 20 个 URL
# 
# [Pagination] ✓ 翻页成功，当前第 2 页
# 
# [Collect-XPath] ===== 第 2 页 =====
# ...
# 
# [Collect-XPath] 收集完成!
#   - 共翻页 5 页
#   - 收集到 100 个 URL

# 运行生成的爬虫脚本
python output/spider.py
```

## 配置参数

可通过以下方式配置：

### 1. 环境变量 (`.env`)
```bash
MAX_PAGES=10                    # 最大翻页次数 ⭐
TARGET_URL_COUNT=50             # 目标 URL 数量
MAX_SCROLLS=20                  # 单页最大滚动次数
NO_NEW_URL_THRESHOLD=3          # 连续无新 URL 阈值
```

### 2. 代码配置
```python
from autospider import URLCollector

collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集招标公告",
    explore_count=3,
    output_dir="output"
)

result = await collector.run()
```

## 功能特点

✅ **自动识别** - 无需手动配置分页选择器
✅ **智能翻页** - 自动检测禁用状态，避免无限循环
✅ **多重备用** - 常规选择器 + LLM 视觉识别
✅ **配置持久化** - pagination_xpath 保存到配置文件
✅ **灵活控制** - 支持最大页数、目标数量等停止条件
✅ **兼容性强** - 支持多种分页格式和 UI 框架

## 技术亮点

1. **策略模式**: 常规选择器 → LLM 视觉识别
2. **智能判断**: 检查禁用、可见性、翻页成功
3. **配置复用**: xpath 缓存和持久化
4. **健壮性**: 多重备用方案，防止失败

## 测试建议

建议测试场景：
1. ✅ 标准分页（文字"下一页"）
2. ✅ 图标分页（箭头 `>`）
3. ✅ UI 框架分页（Ant Design, Element UI）
4. ✅ 禁用状态检测（最后一页）
5. ✅ 无分页情况（单页列表）
6. ✅ 多页翻页（超过 3 页）

## 后续优化方向

- [ ] 支持 Ajax 动态加载分页
- [ ] 支持无限滚动
- [ ] 支持页码跳转
- [ ] 支持分页参数提取（URL 参数）
- [ ] 优化翻页等待时间
- [ ] 添加翻页进度条

## 总结

分页爬取功能已完全集成到 AutoSpider 中，系统现在可以：

1. **自动识别分页控件** - 提取 pagination_xpath
2. **自动翻页收集** - 在收集阶段遍历多页
3. **持久化配置** - 保存到 collection_config.json
4. **智能备用方案** - LLM 视觉识别

所有功能已在代码中实现，文档已完善，可以直接使用！
