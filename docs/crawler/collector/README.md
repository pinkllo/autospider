# 导航与分页处理器 (Collector Components)

`crawler.collector` 包含负责处理页面交互核心逻辑的组件，主要包括导航、分页、URL 提取和 XPath 自动应用。

---

## 📁 主要组件

### 1. `NavigationHandler`
负责根据 LLM 指令执行单步导航动作（点击、按键）。
- **GuardedPage 适配**: 确保所有操作均在受限的页面代理下进行。
- **干扰跳跃**: 能够识别并自动跳过覆盖在目标元素上的弹窗或遮罩。

### 2. `PaginationHandler`
处理复杂的翻页逻辑：
- **模式识别**: 自动识别“下一页”按钮、数字页码或跳转输入框。
- **状态维护**: 跟踪当前已采集的页数。

### 3. `URLExtractor`
从当前页面提取详情页链接。
- **SoM 辅助**: 利用模型对链接文本的理解进行精细化过滤。
- **去重逻辑**: 配合 `RedisQueueManager` 实现全局 URL 去重。

### 4. `XPathExtractor`
当探索阶段沉淀出公共 XPath 后，该组件负责直接应用这些 XPath 进行高速采集，无需再次调用 LLM。

---

*最后更新: 2026-01-27*
