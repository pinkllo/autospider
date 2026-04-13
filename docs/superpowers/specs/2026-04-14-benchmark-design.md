# AutoSpider Benchmark —— 闭环评测系统设计规范

> 日期：2026-04-14
> 状态：设计通过，待实现

## 1. 概述

为 AutoSpider 构建一个端到端闭环评测系统。该系统包含：

1. **模拟网站**（TechMart 科技商城）—— 覆盖列表+详情+翻页、分类分组、动态加载、布局变体、嵌套导航等真实采集场景
2. **测试题集**—— 每个场景对应一条自然语言任务输入和精确的 JSONL 标准答案
3. **评估引擎**—— 对比采集结果与 ground truth，计算准确性/效率/稳定性指标
4. **报告系统**—— 生成 JSON + Markdown 报告，支持跨版本对比
5. **双入口**—— `autospider benchmark` CLI + `pytest -m benchmark` 集成

## 2. 项目结构

```text
tests/benchmark/
├── __init__.py
├── conftest.py                    # pytest fixtures（启动模拟网站服务器等）
├── cli.py                         # `autospider benchmark` CLI 入口
├── runner.py                      # 基准测试运行器核心逻辑
├── evaluator.py                   # 评估引擎（对比采集结果与 ground truth）
├── metrics.py                     # 指标计算（Precision/Recall/F1/步骤数等）
├── reporter.py                    # 报告生成器（Markdown + JSON）
├── mock_site/                     # 模拟网站（所有静态资源）
│   ├── server.py                  # 轻量静态文件服务器（pytest fixture 用）
│   ├── shared/                    # 全站共享资源（CSS/JS/布局模板）
│   │   ├── style.css
│   │   ├── pagination.js          # 翻页逻辑
│   │   ├── dynamic_load.js        # 动态加载/展开逻辑
│   │   └── tabs.js                # Tab 切换逻辑
│   └── scenarios/                 # 各场景的页面文件
│       ├── products/              # 场景1：基础列表+详情+翻页
│       │   ├── index.html         # 列表页
│       │   ├── detail_1.html      # 详情页
│       │   └── ...
│       ├── categories/            # 场景2：分类分组采集
│       ├── dynamic/               # 场景3：动态加载内容
│       ├── variants/              # 场景4：不同布局变体
│       └── nested/                # 场景5：嵌套多层级导航
├── scenarios/                     # 场景定义（与 mock_site/scenarios/ 一一对应）
│   ├── __init__.py
│   ├── schema.py                  # 场景规范的 Pydantic 模型
│   ├── products.yaml              # 场景1 定义（任务输入 + ground truth 路径）
│   ├── categories.yaml
│   ├── dynamic.yaml
│   ├── variants.yaml
│   └── nested.yaml
├── ground_truth/                  # 标准答案（JSONL 文件）
│   ├── products.jsonl
│   ├── categories.jsonl
│   ├── dynamic.jsonl
│   ├── variants.jsonl
│   └── nested.jsonl
└── reports/                       # 生成的评测报告（gitignore）
    ├── 2026-04-14_full_report.json
    └── 2026-04-14_full_report.md
```

### 设计决策

- 模拟网站页面和场景定义**分开存放**——页面文件在 `mock_site/scenarios/`，场景配置在 `scenarios/*.yaml`，ground truth 在 `ground_truth/*.jsonl`。职责清晰。
- `reports/` 目录加入 `.gitignore`，不追踪生成的报告。
- 共享的 JS 逻辑（翻页、动态加载、Tab 切换）放在 `shared/`，各场景复用。

## 3. 模拟网站架构

### 站点主题：TechMart 科技商城

一个虚构的科技产品商城，自然地包含所有需要测试的场景。

### 技术方案

**混合方案**：静态 HTML 为主体（页面结构和数据都预设），前端 JS 处理翻页/动态加载/Tab 切换等交互逻辑，用 pytest fixture 启动一个简单的静态文件服务器。

### 场景 1：Products（基础列表+详情+翻页）

```
/scenarios/products/index.html     → 产品列表页，每页 5 条，共 3 页（15 条）
/scenarios/products/detail_N.html  → 产品详情页 ×15
```

- 列表页有标准分页导航（上一页 / 1 / 2 / 3 / 下一页）
- 每条产品在列表页显示：名称、缩略图、简要价格
- 详情页包含完整字段：名称、价格、品牌、规格参数、描述文本、产品URL
- 字段类型覆盖：文本(`name`)、数字(`price`)、URL(`product_url`)

### 场景 2：Categories（分类分组采集）

```
/scenarios/categories/index.html   → 顶部 Tab 切换 3 个分类：手机 / 电脑 / 配件
```

- 点击 Tab 切换分类，每个分类下有 5 条产品，使用 JS 动态显示/隐藏
- 每个分类内点击进入对应的详情页
- 测试目标：`group_by=category` ，验证系统能正确发现 3 个分类并按分类采集

### 场景 3：Dynamic（动态加载内容）

```
/scenarios/dynamic/index.html      → 列表页，初始显示 3 条，「加载更多」按钮
/scenarios/dynamic/detail_N.html   → 详情页，部分字段在「展开详情」折叠面板内
```

- 列表页点击「加载更多」按钮追加下一批 3 条（共 9 条，需点击 2 次）
- 详情页中「技术参数」部分默认折叠，需点击展开才能看到
- 测试重点：系统需要自主发现并执行点击交互

### 场景 4：Variants（不同页面布局变体）

```
/scenarios/variants/index.html     → 列表页（标准网格布局）
/scenarios/variants/card_N.html    → 卡片式详情页（布局 A）
/scenarios/variants/table_N.html   → 表格式详情页（布局 B）
```

- 同一列表页的链接分别指向两种不同布局的详情页
- 卡片式：字段分散在 div 结构中
- 表格式：字段在 `<table>` 行内
- 测试重点：XPath 归纳引擎能否适应不同 DOM 结构

### 场景 5：Nested（嵌套多层级分类树）

```
/scenarios/nested/index.html       → 侧栏树形导航（3 层：大类 → 中类 → 小类）
/scenarios/nested/list_N.html      → 叶子分类的列表页
/scenarios/nested/detail_N.html    → 详情页
```

- 侧栏展示层级树：电子产品 → 手机 → 智能手机 / 功能机
- 只有叶子节点有产品列表
- 测试重点：系统能否理解多层导航结构并正确定位到叶子分类

### 数据生成原则

- 所有产品数据**硬编码**在 HTML 中（确定性，不依赖外部数据源）
- 字段值设计为**可区分**的（如品牌名不重复、价格各不相同），方便精确匹配
- 每个场景数据量精简（10~15 条），足够验证但不会让测试耗时过长

## 4. 场景规范格式

### YAML 场景定义

每个场景一个 YAML 文件，定义任务输入、预期配置和评估规则：

```yaml
# scenarios/products.yaml
scenario:
  id: products
  name: "基础列表+详情+翻页"
  description: "验证标准列表页翻页和多字段详情页提取"

task:
  # 喂给 chat-pipeline -r 的自然语言指令
  request: "采集 {base_url}/scenarios/products/ 上所有产品的名称、价格、品牌和规格参数"
  # 传给 chat-pipeline 的 CLI 参数覆盖
  cli_overrides:
    max_pages: 5
    serial_mode: true
    headless: true
    output_dir: ".tmp/benchmark/products"

ground_truth:
  file: "ground_truth/products.jsonl"
  record_count: 15
  fields:
    - name: "product_name"
      type: "text"
      required: true
    - name: "price"
      type: "number"
      required: true
    - name: "brand"
      type: "text"
      required: true
    - name: "specs"
      type: "text"
      required: false

evaluation:
  # 记录匹配的主键字段（用于对齐采集结果和 ground truth）
  match_key: "product_name"
  # 字段匹配策略
  field_matching:
    product_name: exact       # 精确匹配
    price: numeric_tolerance   # 数值容差（±0.01）
    brand: exact
    specs: fuzzy              # 模糊匹配（相似度 ≥ 0.85）
  # pass/fail 门槛
  thresholds:
    min_record_recall: 0.8     # 至少采到 80% 的记录
    min_field_f1: 0.7          # 字段级 F1 ≥ 0.7
    max_steps: 50              # 最大步骤数
```

### Ground Truth JSONL 格式

```jsonl
{"product_name": "Galaxy S25 Ultra", "price": 9999.00, "brand": "Samsung", "specs": "6.9英寸 AMOLED, 骁龙8 Gen4, 12GB RAM"}
{"product_name": "iPhone 16 Pro", "price": 8999.00, "brand": "Apple", "specs": "6.7英寸 OLED, A18 Pro, 8GB RAM"}
```

### Pydantic Schema（`scenarios/schema.py`）

场景 YAML 的结构用 Pydantic 模型校验，确保配置合法。

### URL 占位符替换

场景 YAML 中的 URL 使用 `{base_url}` 占位符。Runner 启动时用实际的 `http://localhost:PORT` 替换。

## 5. 评估引擎

### 核心流程（`evaluator.py`）

```
输入:
  - 采集结果 JSONL (actual)
  - 标准答案 JSONL (expected)
  - 场景评估配置 (evaluation config)

流程:
  1. 记录对齐：用 match_key 将 actual 和 expected 逐条配对
  2. 字段级评估：对每条配对记录，按 field_matching 策略逐字段对比
  3. 指标计算：汇总 Precision/Recall/F1
  4. 门槛判断：依据 thresholds 判定 pass/fail

输出:
  - ScenarioResult 对象（包含所有级别的指标）
```

### 字段匹配策略

| 策略 | 说明 | 适用 |
|------|------|------|
| `exact` | 字符串精确相等（strip 后） | 名称、品牌 |
| `numeric_tolerance` | 数值差 ≤ 容差（默认 0.01） | 价格 |
| `fuzzy` | 字符串相似度 ≥ 阈值（默认 0.85，用 SequenceMatcher） | 长文本描述 |
| `contains` | actual 包含 expected 的关键词 | 规格参数 |

## 6. 指标体系

### 6.1 采集准确性指标（每场景）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| `record_precision` | 正确匹配记录 / 采集记录总数 | 采了多少是对的 |
| `record_recall` | 正确匹配记录 / ground truth 记录总数 | 该采的采了多少 |
| `record_f1` | 2×P×R / (P+R) | 记录级综合 |
| `field_precision` | 各字段—正确字段值 / 实际提取字段值 | 字段级准确 |
| `field_recall` | 各字段—正确字段值 / 应有字段值 | 字段级完整 |
| `field_f1` | 各字段 F1 的加权平均 | 字段级综合 |
| `exact_match_rate` | 所有字段完全正确的记录 / 匹配记录 | 完美记录比例 |

### 6.2 流程效率指标（每场景）

| 指标 | 来源 | 说明 |
|------|------|------|
| `total_graph_steps` | LangGraph 节点执行计数 | 主图走了多少步（不包含 LLM 生成时长） |
| `llm_call_count` | LLM trace 累计 | 总 LLM 调用次数 |
| `llm_total_tokens` | LLM trace 累计 | 总 token 消耗 |
| `browser_navigation_count` | Playwright 页面跳转计数 | 浏览器导航次数 |
| `browser_action_count` | 包含点击/输入等交互 | 浏览器交互总次数 |

> 注：端到端耗时使用步骤数而非时钟时间，排除 LLM 生成延迟对指标的干扰。

### 6.3 系统稳定性指标（每场景）

| 指标 | 来源 | 说明 |
|------|------|------|
| `task_success` | 最终的 graph status | 成功 / 失败 / 部分成功 |
| `replan_count` | world model 反馈循环次数 | 重规划触发次数 |
| `subtask_total` | pipeline 结果 | 子任务总数 |
| `subtask_success_count` | pipeline 结果 | 成功子任务数 |
| `subtask_failure_count` | pipeline 结果 | 失败子任务数 |

### 6.4 指标收集方式

设计 `BenchmarkInstrumentation` 类，在测试运行期间采集效率指标：

- **LLM 调用**：装饰/Hook 现有的 LLM 调用层（`common/llm/`），累计调用次数和 token
- **图步骤**：从 LangGraph 的 checkpointer 或执行日志中提取节点执行序列
- **浏览器操作**：Hook `BrowserRuntimeSession` 的导航和操作方法，计数

## 7. 报告系统

### JSON 报告（机器可读）

```json
{
  "run_id": "2026-04-14T01:30:00",
  "git_commit": "c764463",
  "scenarios": {
    "products": {
      "status": "pass",
      "accuracy": { "record_f1": 0.93, "field_f1": 0.88, "exact_match_rate": 0.80 },
      "efficiency": { "total_graph_steps": 23, "llm_call_count": 12, "llm_total_tokens": 15420 },
      "stability": { "task_success": true, "replan_count": 0, "subtask_success_count": 1 }
    }
  },
  "overall": {
    "scenarios_passed": 4,
    "scenarios_failed": 1,
    "avg_record_f1": 0.91,
    "avg_field_f1": 0.85
  }
}
```

### Markdown 报告（人类可读）

包含：汇总表格 + 每场景详情 + 与上次运行的 diff 对比（如果 reports/ 中有历史记录）。

## 8. CLI 与 pytest 集成

### CLI 入口

注册到现有 `cli.py` 的 typer app 中：

```bash
# 运行所有场景
autospider benchmark --all

# 运行指定场景
autospider benchmark --scenario products --scenario categories

# 列出可用场景
autospider benchmark --list

# 查看最近一次报告
autospider benchmark --report latest

# 与上次运行对比
autospider benchmark --all --compare-last
```

### pytest 集成

```python
# tests/benchmark/conftest.py
@pytest.fixture(scope="session")
def mock_site_server():
    """启动模拟网站静态文件服务器，整个测试 session 共享。"""
    server = MockSiteServer(port=0)  # 随机端口
    server.start()
    yield server
    server.stop()

@pytest.fixture(scope="session")
def benchmark_base_url(mock_site_server):
    return f"http://localhost:{mock_site_server.port}"
```

```python
# tests/benchmark/test_benchmark.py
@pytest.mark.benchmark
@pytest.mark.parametrize("scenario_id", ["products", "categories", "dynamic", "variants", "nested"])
def test_scenario(scenario_id, mock_site_server, benchmark_base_url):
    """每个场景作为独立 test case。"""
    scenario = load_scenario(scenario_id)
    result = run_scenario(scenario, base_url=benchmark_base_url)
    
    assert result.accuracy.record_recall >= scenario.thresholds.min_record_recall
    assert result.accuracy.field_f1 >= scenario.thresholds.min_field_f1
    assert result.efficiency.total_graph_steps <= scenario.thresholds.max_steps
```

运行方式：

```bash
# pytest 入口
pytest tests/benchmark -m benchmark -q

# 只跑一个场景
pytest tests/benchmark -m benchmark -k "products" -q
```

## 9. 排除项

以下场景**不在本次设计范围内**：

- 登录/认证场景（Guard 介入）
- 反爬/人机验证模拟
- 无数据/错误页面等异常场景
- 多粒度任务描述变体
