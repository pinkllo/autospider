# AutoSpider 工作流程概览

## 整体架构

AutoSpider 采用**两阶段**架构：
1. **URL 收集阶段**: 使用 `url_collector.py` 收集所有详情页 URL（支持分页）
2. **详情页爬取阶段**: 使用生成的 `spider.py` 批量爬取详情页内容

这种设计的优势：
- ✅ **分离关注点**: URL 收集和内容爬取独立运行
- ✅ **可恢复性**: 可以暂停和继续，无需重新收集 URL
- ✅ **可配置**: URLs 可以手动编辑、去重、过滤
- ✅ **高效**: URL 收集只运行一次，内容爬取可以并发

---

## 阶段 1: URL 收集（url_collector.py）

### Phase 1: 导航到列表页
- 打开目标列表页
- 等待页面加载

### Phase 2: 导航阶段（筛选操作）
- LLM 根据任务描述点击筛选条件
- 例如：点击 "已中标"、"交通运输" 等标签
- 记录每个导航步骤的 XPath

**输出**: `nav_steps` - 导航步骤列表

### Phase 3: 探索阶段
- 进入 N 个不同的详情页（默认 3 个）
- 记录每次进入详情页的操作
- 记录点击元素的 XPath 候选

**输出**: `detail_visits` - 详情页访问记录

### Phase 3.5: 提取公共 XPath
- 分析多次访问的共同模式
- 提取详情链接的公共 XPath

**输出**: `common_detail_xpath` - 例如 `//div[@class='list']//a[@class='title']`

### Phase 3.6: 提取分页控件 XPath ⭐ 新功能
- 自动识别"下一页"按钮
- 提取分页控件的 XPath

**策略**:
1. 常规选择器：尝试预定义的选择器列表
2. LLM 视觉识别：如果常规方法失败，使用 LLM 识别

**输出**: `pagination_xpath` - 例如 `//a[contains(text(), '下一页')]`

### Phase 4: 收集阶段（支持分页）⭐ 新功能

#### 方式 1: 使用 XPath 收集（推荐）
```python
while current_page <= max_pages:
    # 当前页滚动收集
    while scroll_count < max_scrolls:
        elements = page.locator(xpath=common_detail_xpath)
        # 提取 URL（优先从 href，否则点击）
    
    # 翻页到下一页
    if not find_and_click_next_page():
        break  # 已到最后一页
```

#### 方式 2: 使用 LLM 收集（备用）
- 如果没有公共 XPath，使用 LLM 视觉识别详情链接
- 也支持分页

**停止条件**:
- 达到目标数量 (`target_url_count`)
- 达到最大页数 (`max_pages`)
- 连续多次无新 URL (`no_new_url_threshold`)
- 无法翻页（已到最后一页）

**输出**: `collected_urls` - URL 列表

### Phase 4.5: 持久化配置 ⭐ 新功能
保存配置到 `output/collection_config.json`:
```json
{
  "nav_steps": [...],
  "common_detail_xpath": "//div[@class='list']//a",
  "pagination_xpath": "//a[contains(text(), '下一页')]",
  "list_url": "https://example.com/list",
  "task_description": "收集招标公告",
  "created_at": "2026-01-06T10:00:00",
  "updated_at": "2026-01-06T10:30:00"
}
```

**作用**:
- 记录爬虫配置，方便后续使用
- `script_generator.py` 可以从配置文件读取参数
- 支持配置的恢复和复用

### Phase 5: 生成爬虫脚本
使用 `script_generator.py` 生成 `spider.py`

**输出**: `output/spider.py` - 详情页爬虫脚本

### 输出文件
1. `output/urls.txt` - 收集到的所有 URL
2. `output/collection_config.json` - 配置信息（包含 `pagination_xpath`）
3. `output/spider.py` - 生成的爬虫脚本
4. `output/collected_urls.json` - 完整的收集结果（包括元数据）
5. `screenshots/` - 截图记录

---

## 阶段 2: 详情页爬取（spider.py）

### 1. 加载 URL 列表
```python
urls = load_urls()  # 从 output/urls.txt 读取
```

### 2. 启动浏览器
```python
async with async_playwright() as p:
    browser = await p.chromium.launch()
    page = await browser.new_page()
```

### 3. 批量爬取
```python
for url in urls:
    data = await crawl_one(url)
    results.append(data)
```

### 4. 保存结果
```python
# 保存到 output/results.json
json.dump(results, f)
```

---

## 配置参数

### URL 收集器配置 (`config.py`)

```python
class URLCollectorConfig(BaseModel):
    # 探索阶段进入的详情页数量
    explore_count: int = 3
    
    # 单页最大滚动次数
    max_scrolls: int = 20
    
    # 连续无新 URL 的滚动次数后停止
    no_new_url_threshold: int = 3
    
    # 目标 URL 数量（达到后停止）
    target_url_count: int = 5
    
    # 最大翻页次数（新增）⭐
    max_pages: int = 10
```

### 环境变量配置 (`.env`)

```bash
# 探索配置
EXPLORE_COUNT=3

# 滚动配置
MAX_SCROLLS=20
NO_NEW_URL_THRESHOLD=3

# 收集配置
TARGET_URL_COUNT=50
MAX_PAGES=10  # 最大翻页次数 ⭐

# LLM 配置
AIPING_API_KEY=your_api_key
AIPING_API_BASE=https://api.siliconflow.cn/v1
AIPING_MODEL=zai-org/GLM-4.6V

# 浏览器配置
HEADLESS=false
VIEWPORT_WIDTH=1280
VIEWPORT_HEIGHT=720
```

---

## 分页爬取功能详解 ⭐

### 1. 自动识别分页按钮

**支持的格式**:
- 文字: `下一页`, `下页`, `>`, `>>`, `Next`
- Class: `next`, `pagination-next`, `ant-pagination-next`
- 属性: `aria-label="下一页"`, `title="下一页"`
- UI 框架: Ant Design, Element UI, Bootstrap

### 2. 智能翻页策略

```python
# 优先使用探索阶段提取的 pagination_xpath
if pagination_xpath:
    click(pagination_xpath)
else:
    # 尝试常见选择器
    for selector in next_page_selectors:
        if find(selector):
            click(selector)
            break
```

### 3. 健壮性保障

- ✅ 检查按钮是否禁用
- ✅ 检查按钮是否可见
- ✅ 验证翻页是否成功
- ✅ LLM 视觉识别作为备用方案

### 4. 翻页日志

```
[Pagination] 尝试翻页...
[Pagination] 使用已提取的 xpath: //a[contains(text(), '下一页')]
[Pagination] ✓ 翻页成功，当前第 2 页
```

---

## 使用示例

### 完整流程

```python
# 1. 运行 URL 收集器（自动分页）
from autospider import URLCollector

collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集招标公告详情页",
    explore_count=3,
    output_dir="output"
)

result = await collector.run()
# 输出: 已收集 100 个 URL（共翻页 10 页）

# 2. 运行生成的爬虫脚本
python output/spider.py
# 输出: 爬取完成! 成功 100/100 个
```

### 从配置恢复

```python
from autospider.persistence import ConfigPersistence

persistence = ConfigPersistence("output")
config = persistence.load()

if config:
    print(f"公共 XPath: {config.common_detail_xpath}")
    print(f"分页 XPath: {config.pagination_xpath}")
    print(f"导航步骤: {len(config.nav_steps)} 个")
```

---

## 目录结构

```
output/
├── urls.txt                    # 收集的 URL 列表
├── collection_config.json      # 配置信息（包含 xpath）⭐
├── collected_urls.json         # 完整收集结果
├── spider.py                   # 生成的爬虫脚本
└── results.json               # 爬取的详情页数据

screenshots/
├── explore_1.png              # 探索阶段截图
├── explore_2.png
├── pagination_extract.png     # 分页提取截图 ⭐
└── collect_*.png              # 收集阶段截图
```

---

## 性能特点

### URL 收集阶段
- **速度**: 快速（仅收集 URL，不爬取内容）
- **分页**: 自动翻页，支持最多 N 页
- **智能**: LLM 视觉识别 + XPath 提取
- **可靠**: 多重备用方案

### 详情页爬取阶段
- **速度**: 可配置并发（当前为串行）
- **简单**: 无需 Scrapy，纯 Playwright
- **稳定**: 直接读取 URL 列表

---

## 常见问题

### Q1: 为什么分两个阶段？
A: 分离 URL 收集和内容爬取，提高可维护性和可恢复性。

### Q2: 分页功能如何工作？
A: 自动识别"下一页"按钮，提取 XPath，在收集阶段自动翻页。

### Q3: 如果识别不到分页按钮怎么办？
A: 系统会尝试常见选择器列表，如果仍失败会使用 LLM 视觉识别。

### Q4: 可以限制翻页次数吗？
A: 可以，通过 `MAX_PAGES` 环境变量或 `config.url_collector.max_pages` 配置。

### Q5: URLs 可以手动编辑吗？
A: 可以！`urls.txt` 是纯文本文件，可以手动添加、删除或修改 URL。

---

## 下一步优化

- [ ] 支持详情页爬取的并发执行
- [ ] 支持断点续爬
- [ ] 支持代理池
- [ ] 支持更多分页类型（Ajax 动态加载、无限滚动等）
- [ ] 支持详情页内容的结构化提取
- [ ] WebUI 可视化界面
