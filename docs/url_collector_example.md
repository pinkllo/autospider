# URL 收集器使用示例

## 功能说明

URL 收集器通过 LLM 智能识别详情页链接，自动探索、分析模式并批量收集所有详情页 URL。

## 使用方法

### 基本用法

```bash
autospider collect-urls \
  --list-url "https://ygp.gdzwfw.gov.cn/#/44/jygg" \
  --task "收集招标公告详情页" \
  --explore-count 3
```

### 参数说明

- `--list-url` (必需): 列表页的 URL
- `--task` (必需): **任务描述**，用自然语言描述你想收集哪些详情页
  - 例如："收集招标公告详情页"
  - 例如："收集新闻文章详情页"
  - 例如："收集产品详情页"
- `--explore-count`: 探索几个详情页来学习模式（默认 3）
- `--headless`: 是否使用无头模式（默认否）
- `--output`: 输出目录（默认 "output"）

## 工作流程

### 1. 智能识别阶段

LLM 会根据你的任务描述，智能识别列表页中的目标详情链接：

```
[LLM] 识别到 5 个候选链接
[LLM] 推理: 这些元素都是招标公告的标题链接，点击后会进入详情页...
```

### 2. 探索阶段

自动进入 N 个不同的详情页，记录访问路径：

```
[Explore] 步骤 1: 点击元素 [12] "某某项目招标公告..."
[Visit] 成功进入详情页: https://example.com/detail/123
[Explore] 已探索 1/3 个详情页
```

### 3. 分析阶段

分析多次访问的共同模式：

```
[Pattern] 提取到的模式:
  - 标签: a
  - 角色: link
  - 链接模式: ^/detail/.*
  - 置信度: 80%
```

### 4. 收集阶段

使用提取的模式遍历列表页，收集所有匹配的 URL：

```
[Collect] 当前已收集 156 个 URL
[Collect] 滚动完成，共滚动 18 次
```

## 输出结果

### 文件输出

1. **collected_urls.json**: 完整的收集结果（JSON 格式）
   - 包含任务描述
   - 探索记录
   - 公共模式
   - 收集到的 URL 列表

2. **urls.txt**: 纯 URL 列表（每行一个 URL）
   ```
   https://example.com/detail/1
   https://example.com/detail/2
   https://example.com/detail/3
   ...
   ```

3. **screenshots/**: 探索过程的截图
   - `step_001_before_click.png`: 点击前的列表页
   - `step_001_detail_page.png`: 进入后的详情页
   - ...

### 终端输出示例

```
[URLCollector] ===== 开始收集详情页 URL =====
[URLCollector] 任务描述: 收集招标公告详情页
[URLCollector] 列表页: https://ygp.gdzwfw.gov.cn/#/44/jygg
[URLCollector] 将探索 3 个详情页

[Phase 1] 导航到列表页...

[Phase 2] 探索阶段：进入 3 个详情页...
[LLM] 识别到 8 个候选链接
[LLM] 推理: 这些都是招标公告的标题链接...
[Visit] 步骤 1: 点击元素 [15] "某某工程招标公告"
[Visit] 成功进入详情页: https://...
[Explore] 已探索 1/3 个详情页
...

[Phase 3] 分析阶段：提取公共模式...
[Pattern] 提取到的模式:
  - 标签: a
  - 角色: link
  - 链接模式: ^/#/44/jygg/detail/.*
  - 置信度: 90%

[Phase 4] 收集阶段：遍历列表页收集所有 URL...
[Collect] 当前已收集 50 个 URL
[Collect] 当前已收集 103 个 URL
[Collect] 滚动完成，共滚动 15 次

[Complete] 收集完成!
  - 探索了 3 个详情页
  - 收集到 156 个详情页 URL
```

## 使用技巧

### 1. 精确的任务描述

任务描述要清晰具体，帮助 LLM 准确识别目标链接：

✅ **好的描述**：
- "收集招标公告详情页"
- "收集新闻文章详情页（排除广告链接）"
- "收集产品详情页（只要产品，不要分类页）"

❌ **不好的描述**：
- "收集详情页"（太模糊）
- "点击链接"（没有说明目标）

### 2. 调整探索数量

- 列表页链接格式统一：`--explore-count 2` 即可
- 列表页有多种链接类型：建议 `--explore-count 5`
- 链接格式复杂多变：可增加到 `--explore-count 10`

### 3. 处理分页

如果列表页有分页，收集器会自动滚动：
- 默认最多滚动 20 次（可在配置中调整）
- 连续 3 次滚动没有新 URL 则停止

### 4. 验证结果

收集完成后，建议：
1. 查看 `urls.txt` 确认数量
2. 随机抽查几个 URL 确认准确性
3. 查看 `collected_urls.json` 了解提取的模式

## 常见问题

### Q: LLM 识别不准确怎么办？

A: 尝试优化任务描述，添加更多细节。例如：
```bash
--task "收集招标公告详情页，这些链接通常是项目标题，包含'招标'、'采购'等关键词"
```

### Q: 收集到的 URL 有重复怎么办？

A: 收集器会自动去重，如果仍有重复，可能是 URL 参数不同但指向同一页面。

### Q: 如何处理需要登录的页面？

A: 当前版本暂不支持自动登录，可以先手动登录后再使用收集器。

### Q: 收集速度慢怎么办？

A: 
1. 使用 `--headless` 模式
2. 减少 `--explore-count`
3. 调整配置中的滚动参数

## 高级用法

### 编程方式调用

```python
import asyncio
from src.autospider.browser import create_browser_session
from src.autospider.url_collector import collect_detail_urls

async def collect():
    async with create_browser_session(headless=True) as session:
        result = await collect_detail_urls(
            page=session.page,
            list_url="https://example.com/list",
            task_description="收集招标公告详情页",
            explore_count=3,
            output_dir="output/my_collection",
        )
        
        print(f"收集到 {len(result.collected_urls)} 个 URL")
        return result.collected_urls

urls = asyncio.run(collect())
```

### 批量处理多个列表页

```bash
# 创建脚本 collect_all.sh
#!/bin/bash

autospider collect-urls --list-url "https://site.com/list1" --task "收集新闻" --output output/list1
autospider collect-urls --list-url "https://site.com/list2" --task "收集公告" --output output/list2
autospider collect-urls --list-url "https://site.com/list3" --task "收集文章" --output output/list3
```
