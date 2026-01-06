# URL 收集器工作原理详解

## URL 获取的完整流程

### 阶段 1: 导航阶段（筛选）

```
用户输入: "爬取已中标的交通运输项目"
    ↓
LLM 分析任务
    ↓
点击筛选条件:
  - 点击"已中标"标签
  - 点击"交通运输"分类
    ↓
等待筛选结果加载
```

### 阶段 2: 探索阶段（学习模式）

#### 步骤 1: 识别详情链接

```python
# 1. 扫描页面，获取所有可交互元素
snapshot = await inject_and_scan(self.page)

# 2. LLM 根据任务描述识别目标链接
candidates = await self._find_detail_link_candidates_with_llm(snapshot)
# 返回: [ElementMark1, ElementMark2, ...]
# 每个 ElementMark 包含:
#   - mark_id: 元素编号
#   - text: 元素文本（如"某某项目中标公告"）
#   - href: 链接地址（关键！）
#   - xpath_candidates: XPath 列表
```

#### 步骤 2: 获取并转换 URL

```python
for candidate in detail_candidates:
    href = candidate.href  # 例如: "/#/44/jygg/detail/12345"
    
    # 关键: 将相对 URL 转换为完整 URL
    from urllib.parse import urljoin
    full_url = urljoin(self.list_url, href)
    # 结果: "https://ygp.gdzwfw.gov.cn/#/44/jygg/detail/12345"
    
    # 检查是否已访问
    if full_url not in self.visited_detail_urls:
        visit = await self._visit_detail_page(candidate, snapshot)
```

#### 步骤 3: 访问详情页

```python
async def _visit_detail_page(element, snapshot):
    # 1. 记录当前 URL（列表页）
    list_url = self.page.url
    
    # 2. 点击元素
    locator = self.page.locator(f'[data-som-id="{element.mark_id}"]')
    await locator.first.click(timeout=5000)
    await asyncio.sleep(1.5)  # 等待跳转
    
    # 3. 获取新 URL（详情页）
    new_url = self.page.url  # 关键：从实际页面获取 URL
    
    # 4. 验证是否真的跳转了
    if new_url == list_url:
        print("点击后 URL 未变化，可能不是详情链接")
        return None
    
    # 5. 创建访问记录
    visit = DetailPageVisit(
        list_page_url=list_url,      # 列表页 URL
        detail_page_url=new_url,      # 详情页 URL（从浏览器获取）
        clicked_element_href=element.href,  # 元素的原始 href
        clicked_element_text=element.text,
        clicked_element_xpath_candidates=[...],
    )
    
    return visit
```

### 阶段 3: 分析阶段（提取模式）

```python
# 分析 3 次访问记录，提取公共特征
visits = [visit1, visit2, visit3]

# 1. 标签模式
tags = [v.clicked_element_tag for v in visits]
# 如果都是 "a"，则 tag_pattern = "a"

# 2. 链接模式
hrefs = [v.clicked_element_href for v in visits]
# 例如: ["/#/44/jygg/detail/123", "/#/44/jygg/detail/456", ...]
# 提取共同前缀: "/#/44/jygg/detail/"
# 生成正则: "^/#/44/jygg/detail/.*"

# 3. XPath 模式
xpaths = [v.clicked_element_xpath_candidates[0] for v in visits]
# 找出公共部分
```

### 阶段 4: 收集阶段（批量获取，支持多页）

```python
# 回到列表页开始位置
await self.page.goto(self.list_url, ...)

# 重新执行导航步骤（筛选操作）
if self.nav_steps:
    await self._replay_nav_steps()

# 外层循环：翻页
while self.current_page_num <= max_pages:
    print(f"===== 第 {self.current_page_num} 页 =====")
    
    # 内层循环：当前页滚动收集
    while scroll_count < max_scrolls:
        # 1. 扫描当前视图
        snapshot = await inject_and_scan(self.page)
        
        # 2. 使用提取的模式匹配元素
        matched_elements = self._match_elements_by_pattern(snapshot, pattern)
        
        # 3. 收集所有匹配元素的 URL
        for elem in matched_elements:
            url = elem.href
            if url and url not in self.collected_urls:
                url = urljoin(self.list_url, url)
                self.collected_urls.append(url)
        
        # 4. 滚动到下一屏
        await self.page.evaluate("window.scrollBy(0, 500)")
    
    # 5. 尝试翻页
    page_turned = await self._find_and_click_next_page()
    if not page_turned:
        # 如果常规方法找不到，尝试用 LLM 视觉识别
        page_turned = await self._find_next_page_with_llm(screenshot_base64)
    
    if not page_turned:
        print("无法翻页，结束收集")
        break
```

### 分页功能详解

#### 翻页按钮识别策略

**策略 1: 常见选择器匹配**
```python
next_page_selectors = [
    # 文字类
    "//a[contains(text(), '下一页')]",
    "//button[contains(text(), '下一页')]",
    "//a[contains(text(), '>')]",
    # class 类
    "//*[contains(@class, 'next')]",
    "//li[contains(@class, 'next')]/a",
    # aria-label 类
    "//*[@aria-label='下一页']",
    # UI 框架特定
    "//li[contains(@class, 'ant-pagination-next')]//...",
]
```

**策略 2: LLM 视觉识别**
```python
# 当常见选择器都失败时，使用 LLM 视觉识别
async def _find_next_page_with_llm(self, screenshot_base64):
    prompt = "请找到页面上的下一页按钮..."
    # LLM 返回 mark_id，然后点击
```

#### 配置项

```python
# config.py
class URLCollectorConfig:
    max_pages: int = 10  # 最大翻页次数
    max_scrolls: int = 20  # 每页最大滚动次数
    target_url_count: int = 50  # 目标 URL 数量
```

#### 翻页终止条件

1. 达到目标 URL 数量
2. 达到最大翻页次数
3. 下一页按钮禁用/不存在
4. 连续多次无新 URL

## URL 来源对比

### 探索阶段的 URL

```python
# 来源 1: 元素的 href 属性
element.href  # "/#/44/jygg/detail/12345"

# 来源 2: 实际访问后从浏览器获取（更准确！）
visit.detail_page_url = self.page.url  
# "https://ygp.gdzwfw.gov.cn/#/44/jygg/detail/12345"
```

**为什么使用来源 2？**
- SPA（单页应用）可能通过 JS 跳转，href 可能不准确
- 浏览器的 `page.url` 是实际访问的 URL
- 更可靠，能处理重定向等情况

### 收集阶段的 URL

```python
# 直接从元素的 href 获取
elem.href  # "/#/44/jygg/detail/12345"

# 转换为完整 URL
full_url = urljoin(self.list_url, elem.href)
# "https://ygp.gdzwfw.gov.cn/#/44/jygg/detail/12345"
```

**为什么不点击？**
- 已经有了模式，可以直接提取 href
- 点击太慢，只需要收集 URL 列表
- 批量处理更高效

## 可能的问题和解决方案

### 问题 1: 点击后 URL 未变化

**原因**: 
- 元素不是真正的链接
- SPA 延迟加载
- 需要更长等待时间

**解决**: 
```python
if new_url == list_url:
    print("点击后 URL 未变化")
    return None  # 跳过这个元素
```

### 问题 2: 相对 URL vs 完整 URL

**原因**: 
```python
element.href = "/#/44/jygg/detail/123"  # 相对路径
visited_urls = ["https://ygp.gdzwfw.gov.cn/#/44/jygg/detail/123"]  # 完整路径
```

**解决**: 
```python
full_url = urljoin(self.list_url, href)  # 统一转换为完整 URL
```

### 问题 3: SPA 页面 URL 不变

**症状**: 点击后页面内容变了，但 URL 没变

**解决**: 
- 等待更长时间
- 检查页面内容是否变化
- 使用其他导航方式

## 调试技巧

### 查看截图

```bash
# 探索阶段的截图
output/screenshots/step_001_before_click.png  # 点击前的列表页
output/screenshots/step_001_detail_page.png   # 进入后的详情页
output/screenshots/step_002_before_click.png  # 第二次点击前
...
```

### 查看收集结果

```bash
# URL 列表
output/urls.txt

# 完整结果（包含探索记录和模式）
output/collected_urls.json
```

### 终端日志关键信息

```
[LLM] 识别到 5 个候选链接
[LLM] 推理: 这些元素都是...

[Visit] 步骤 1: 点击元素 [15] "某某项目中标公告"
[Visit] 成功进入详情页: https://...
[Explore] 已探索 1/3 个详情页

[Pattern] 提取到的模式:
  - 标签: a
  - 链接模式: ^/#/44/jygg/detail/.*
  - 置信度: 90%

[Collect] 当前已收集 156 个 URL
```

## 总结

**URL 的获取方式**:

1. **探索阶段**: 从 `self.page.url`（实际访问后）
   - 更准确
   - 能处理 SPA、重定向
   - 但速度慢（需要点击）

2. **收集阶段**: 从 `element.href`（直接提取）
   - 速度快
   - 批量处理
   - 基于已学习的模式

**关键点**: 
- 探索阶段是"学习"，通过实际点击验证
- 收集阶段是"应用"，批量提取 URL
- 两个阶段互补，确保准确性和效率
