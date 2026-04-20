# Crawler Collector 模块

该模块提供了 URL 收集过程中的各种核心处理器和工具函数，采用了高度解耦的设计。

## 核心处理器

- **`URLExtractor`** : 负责从页面中提取链接，支持 XPath 和 LLM 两种模式。
- **`NavigationHandler`** : 处理复杂的页面导航逻辑，支持记录和重放导航步骤。
- **`PaginationHandler`** : 负责识别和执行翻页操作（下一页、加载更多等）。  
- **`LLMDecisionMaker`** : 利用大语言模型对页面元素进行语义分析，做出抓取决策。
- **`XPathExtractor`** : 从多次访问记录中分析并提取公共的 XPath 模式。

## 数据模型与工具

- **`models.py`**: 定义了 `DetailPageVisit`、`URLCollectorResult` 等核心数据结构。
- **`page_utils.py`**: 提供页面滚动 (`smart_scroll`)、触底检测等实用工具。

## 设计目标
通过将导航、分页、提取等逻辑解耦到独立的处理器类中，使得 `URLCollector` 和 `BatchCollector` 可以灵活组合这些组件来完成复杂的抓取任务。
