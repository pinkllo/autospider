# AutoSpider 文档

AutoSpider 是一个基于大语言模型 (LLM) 和 SoM (Set-of-Mark) 标注技术的纯视觉浏览器自动化 Agent，能够自动发现、分析并批量采集网页数据。

---

## 📚 文档目录

### 🏗️ 核心模块
- [**Common 模块**](common/README.md) - 基础设施、浏览器操作 (GuardedPage)、SoM 系统及可靠队列。
- [**Crawler 模块**](crawler/README.md) - 爬取引擎，包含探索、分页导航和断点恢复。
- [**Field 模块**](field/README.md) - 自动字段建模、XPath 沉淀与文本提取。
- [**Pipeline 模块**](pipeline/runner.py.md) - 并行采集流水线（列表生产 + 详情消费）。

### 🛠️ 技术特性
- [**URL 通道**](common/channel/README.md) - 解耦的生产-消费模式。
- [**LLM 交互与协议**](common/llm/README.md) - SoM 决策逻辑与 LLM 协议解析。
- [**断点续传**](crawler/checkpoint/README.md) - 高可靠性的采集任务恢复机制。

### 📋 辅助信息
- [项目流程图](architecture_flowchart.md) - 系统架构和工作流程。
- [疑难解答](troubleshooting/README.md) - 常见问题与解决方案。

---

## 🚀 快速开始

### 1. 安装
```bash
pip install -e .
playwright install chromium
```

### 2. 启动流水线
```python
from autospider.pipeline import run_pipeline
# ... 详见 pipeline 文档
```

---

*最后更新: 2026-01-27*
