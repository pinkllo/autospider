# 并行流水线 (Pipeline)

`pipeline` 模块提供“端到端”的并行采集能力，能够同时启动列表页 URL 收集和详情页数据抽取，极大缩短整体采集时间。

---

## 🚀 核心逻辑：生产-消费者模型

流水线由三个并发运行的协程组成：
1. **Producer (生产者)**: 运行 `URLCollector`，在列表页翻页并发现 URL，发布到 `URLChannel`。
2. **Explorer (探索者)**: 从通道获取前 N 个 URL，运行 `BatchFieldExtractor` 自动分析详情页的公共 XPath 模式。
3. **Consumer (消费者)**: 等待模式准备就绪后，使用 `BatchXPathExtractor` 持续消费通道中的后续 URL，并执行高效率抽取。

---

## 🔧 使用方法

### 命令行入口
```bash
autospider pipeline-run \
  --list-url "https://news.example.com/china" \
  --task "采集所有国内新闻标题和发布日期" \
  --fields-file fields.json \
  --mode redis
```

### 库函数调用
```python
from autospider.pipeline import run_pipeline
from autospider.field import FieldDefinition

summary = await run_pipeline(
    list_url="https://...",
    task_description="...",
    fields=[
        FieldDefinition(name="title", description="标题"),
        FieldDefinition(name="date", description="发布时间")
    ],
    pipeline_mode="memory"
)

print(f"成功采集: {summary['success_count']} 条数据")
```

### 参数详解

- **`list_url`**: 启动采集的列表页起始地址。
- **`task_description`**: 核心指令。指导 AI 如何在页面中定位详情页链接，以及需要从详情页提取哪些具体含义的字段。
- **`fields`**: `FieldDefinition` 列表，定义了目标字段的名称和描述。
- **`explore_count`**: 规则探索量（默认从配置读取）。AI 会深入分析这前几个页面以生成通用的 XPath。
- **`validate_count`**: 规则验证量（默认从配置读取）。用于验证生成的 XPath 是否稳健。
- **`pipeline_mode`**: 指定使用的任务通道模式（`memory`/`file`/`redis`）。

---

## 🛠️ 内部架构与并发控制

- **双浏览器会话**: 流水线内部维护了两个独立的 `BrowserSession`（`list_session` 和 `detail_session`）。这样可以确保列表页的翻页与详情页的抽取互不干扰，避免页面跳转导致的竞争问题。
- **事件同步**:
    - `producer_done`: 当列表页所有 URL 收集完成后触发，通知消费者在队列为空时可以退出。
    - `xpath_ready`: 当探索者生成好通用的 XPath 规则后触发，通知消费者可以开始高效的大规模抽取。

---

## 📁 输出结果
- `output/pipeline_extracted_items.jsonl`: 实时追加的抽取结果。
- `output/pipeline_summary.json`: 运行汇总统计（耗时、成功率、错误信息）。

---

*最后更新: 2026-01-27*
