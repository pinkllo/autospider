# Crawler 模块

Crawler 模块是 AutoSpider 的核心采集引擎，负责处理列表页的探索、URL 收集以及断点续传。

---

## 📁 模块结构

```
crawler/
├── batch/               # 批量采集引擎 (BatchExecutor)
├── checkpoint/          # 断点续传与恢复系统 (Coordinate, RateControl)
├── collector/           # 页面交互组件 (Navigation, Pagination, XPath)
└── explore/             # 任务探索与配置生成 (URLCollector, ConfigGenerator)
```

---

## 🚀 核心子模块介绍

### 1. 探索与生成 (Explore)
使用 LLM 模拟人类视觉，自动在列表页进行筛选、翻页，并进入详情页样本进行分析。
- `URLCollector`: 负责初步的 URL 发现。
- `ConfigGenerator`: 根据探索结果生成可复用的采集配置文件（含 XPath）。

### 2. 交互组件 (Collector)
封装了具体的浏览器操作细节。
- **翻页**: 支持数字、下一页、跳转框。
- **导航**: 处理点击后的页面等待、标签页切换及干扰元素。

### 3. 断点恢复 (Checkpoint)
确保在大规模采集任务中，程序崩溃或重启后能从上次中断的地方继续。
- **协调器**: 自动选择最快的恢复路径（如通过 URL 参数、输入页码等）。
- **限速器**: 根据网站反馈动态调整延迟。

---

*最后更新: 2026-01-27*
