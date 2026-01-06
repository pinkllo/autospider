# 分页爬取快速使用指南

## 快速开始

### 1. 配置环境变量

在 `.env` 文件中添加：

```bash
# 分页配置
MAX_PAGES=10                    # 最多翻多少页
TARGET_URL_COUNT=50             # 收集多少个 URL 后停止
```

### 2. 运行收集命令

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页"
```

### 3. 查看结果

系统会自动：
- ✅ 识别"下一页"按钮
- ✅ 自动翻页收集 URL
- ✅ 保存到 `output/urls.txt`
- ✅ 保存配置到 `output/collection_config.json`

## 输出文件

```
output/
├── urls.txt                    # 所有收集的 URL
├── collection_config.json      # 配置（包含 pagination_xpath）
├── spider.py                   # 生成的爬虫脚本
└── collected_urls.json         # 完整结果
```

## 日志示例

运行时会看到：

```
[Phase 3.6] 提取分页控件 xpath...
[Extract-Pagination] ✓ 找到分页控件 xpath: //a[contains(text(), '下一页')]

[Collect-XPath] ===== 第 1 页 =====
[Collect-XPath] ✓ 当前已收集 20 个 URL

[Pagination] ✓ 翻页成功，当前第 2 页

[Collect-XPath] ===== 第 2 页 =====
[Collect-XPath] ✓ 当前已收集 40 个 URL

[Pagination] ✓ 翻页成功，当前第 3 页

...

[Collect-XPath] 收集完成!
  - 共翻页 5 页
  - 收集到 100 个 URL
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_PAGES` | 10 | 最大翻页次数 |
| `TARGET_URL_COUNT` | 5 | 目标 URL 数量 |
| `MAX_SCROLLS` | 20 | 单页最大滚动次数 |
| `NO_NEW_URL_THRESHOLD` | 3 | 连续无新 URL 阈值 |

## 停止条件

系统会在以下情况停止收集：
1. ✅ 达到目标数量 (`TARGET_URL_COUNT`)
2. ✅ 达到最大页数 (`MAX_PAGES`)
3. ✅ 无法翻页（已到最后一页）
4. ✅ 连续多次无新 URL

## 支持的分页格式

- ✅ 文字: `下一页`, `下页`, `>`, `>>`, `Next`
- ✅ Class: `next`, `pagination-next`
- ✅ 属性: `aria-label="下一页"`, `title="下一页"`
- ✅ UI 框架: Ant Design, Element UI, Bootstrap

## 查看配置

收集完成后，可以查看 `collection_config.json`:

```json
{
  "pagination_xpath": "//a[contains(text(), '下一页')]",
  "common_detail_xpath": "//div[@class='list']//a",
  "nav_steps": [...],
  "list_url": "https://example.com/list",
  "task_description": "收集招标公告"
}
```

## 下一步

收集完 URL 后，运行生成的爬虫脚本爬取详情页：

```bash
python output/spider.py
```

## 常见问题

**Q: 如果识别不到分页按钮怎么办？**
A: 系统会自动使用 LLM 视觉识别作为备用方案。

**Q: 可以限制翻页次数吗？**
A: 可以，通过 `MAX_PAGES` 环境变量配置。

**Q: 如何查看翻了多少页？**
A: 查看日志输出，会显示 "共翻页 X 页"。

**Q: 配置文件有什么用？**
A: 保存了 xpath 配置，可以在后续运行中复用。

## 更多文档

- **详细说明**: `docs/pagination_feature.md`
- **完整流程**: `docs/workflow_overview.md`
- **实现总结**: `docs/pagination_implementation_summary.md`
