# Extractor 模块

Extractor 模块是 AutoSpider 的智能规则发现引擎，负责从页面结构中自动分析和提取关键信息。该模块通过大语言模型（LLM）理解页面语义，结合 Set-of-Mark（SoM）可视化标注技术，实现对复杂网页结构的智能解析。模块能够自动发现列表页与详情页的关联规则、识别分页模式、提取目标数据字段，并最终生成可复用的爬虫配置文件和自动化脚本。

Extractor 模块的核心价值在于降低爬虫开发的门槛。传统爬虫开发需要开发者深入理解目标网站的 HTML 结构，手工编写 XPath 或 CSS 选择器，这一过程耗时且容易出错。Extractor 模块通过 LLM 的语义理解能力，能够自动推断页面元素的含义和功能，将开发者从繁琐的选择器编写工作中解放出来。同时，模块生成的配置文件和脚本具有明确的语义和结构，便于后续维护和复用。

## 模块结构

```
extractor/
├── __init__.py              # 模块入口，导出 ConfigGenerator
├── config_generator.py      # 配置生成器
├── collector/               # 页面信息收集器
│   ├── __init__.py
│   ├── models.py            # 数据模型定义
│   ├── page_utils.py        # 页面操作工具函数
│   ├── url_extractor.py     # URL 提取器
│   ├── xpath_extractor.py   # XPath 模式提取器
│   ├── navigation_handler.py    # 导航处理器
│   ├── pagination_handler.py    # 分页处理器
│   └── llm_decision.py          # LLM 决策模块
├── llm/                     # LLM 相关组件
│   ├── __init__.py
│   ├── planner.py           # 任务规划器
│   ├── decider.py           # 多模态决策器
│   └── prompt_template.py   # 通用 Prompt 模板引擎
├── graph/                   # LangGraph Agent
│   ├── __init__.py
│   └── agent.py             # SoM 视觉 Agent
├── output/                  # 输出生成
│   └── script_generator.py  # 脚本生成器
└── validator/               # 验证器
    ├── __init__.py
    └── mark_id_validator.py # Mark ID 验证器
```

## 核心组件

### ConfigGenerator

ConfigGenerator 是配置生成的核心入口，负责协调各个子组件完成从页面分析到配置生成的完整流程。它封装了页面信息收集、模式分析、LLM 推理等复杂逻辑，对外提供简洁的接口。开发者只需提供起始 URL 和任务描述，ConfigGenerator 就能自动完成剩余的分析工作，最终输出完整的爬虫配置。

ConfigGenerator 的工作流程分为几个关键阶段。首先是页面导航和信息收集阶段，组件会访问起始页面，使用 SoM 技术对页面元素进行标注，并收集必要的信息。其次是模式分析阶段，组件运用 XPathExtractor 从多次页面访问记录中提取公共选择器模式，同时利用 LLM 理解页面的语义结构。最后是配置生成阶段，组件将分析结果整合为结构化的配置文件，包含列表页规则、详情页规则、分页规则等完整定义。

```python
from autospider import ConfigGenerator

generator = ConfigGenerator()

result = await generator.generate(
    list_url="https://example.com/products",
    task_description="采集商品名称、价格、详情描述"
)

print(f"生成的配置：{result.config}")
print(f"生成的脚本：{result.script}")
```

### 数据模型

Extractor 模块定义了一套完整的数据模型用于描述页面访问记录和提取结果。这些模型提供了清晰的数据结构，使得各组件之间的数据传递变得规范和可追踪。

DetailPageVisit 模型记录了一次详情页访问的完整信息，包括入口 URL、点击的元素信息、上下文等。当 URLCollector 探索详情页时，每次点击和导航都会生成一个 Visit 记录，这些记录是后续模式分析的基础数据。

```python
from autospider.extractor.collector.models import DetailPageVisit

visit = DetailPageVisit(
    list_page_url="https://example.com/list",
    detail_page_url="https://example.com/product/123",
    clicked_element_mark_id=5,
    clicked_element_tag="a",
    clicked_element_text="查看详情",
    clicked_element_href="/product/123",
    clicked_element_role="link",
    clicked_element_xpath_candidates=[
        {"xpath": "//section//ul/li[1]/a", "priority": 10},
        {"xpath": "//div[@class='product']/a", "priority": 8}
    ],
    step_index=0,
    timestamp="2024-01-01T10:00:00Z"
)
```

CommonPattern 模型描述了从多次访问中发现的公共模式。这些模式包括元素标签类型、角色属性、文本特征、链接模式等，以及最终的 XPath 公共前缀。置信度字段反映了该模式在样本中的出现频率，是评估模式可靠性的重要指标。

```python
from autospider.extractor.collector.models import CommonPattern

pattern = CommonPattern(
    tag_pattern="a",
    role_pattern="link",
    text_pattern=r".*查看详情.*",
    href_pattern=r"/product/\d+",
    common_xpath_prefix="//section//ul/li",
    xpath_pattern="//section//ul/li/a",
    confidence=0.85,
    source_visits=[visit1, visit2, visit3]
)
```

URLCollectorResult 模型聚合了整个 URL 收集过程的结果，包含探索阶段的所有访问记录、分析阶段发现的公共模式、收集阶段得到的最终 URL 列表，以及相关的元信息。这个结果是配置生成的重要输入。

```python
from autospider.extractor.collector.models import URLCollectorResult

result = URLCollectorResult(
    detail_visits=[visit1, visit2, visit3],
    common_pattern=pattern,
    collected_urls=[
        "https://example.com/product/1",
        "https://example.com/product/2",
        "https://example.com/product/3"
    ],
    list_page_url="https://example.com/list",
    task_description="采集商品详情",
    total_pages_scrolled=5,
    created_at="2024-01-01T10:00:00Z"
)
```

### XPathExtractor

XPathExtractor 专门负责从访问记录中提取公共 XPath 模式。它分析所有 DetailPageVisit 中的 xpath_candidates，通过去掉索引、找出公共前缀等操作，最终得到一个稳定的 XPath 模式。这个模式可以用于批量选择同类元素，是实现自动化采集的关键。

提取算法的核心思路是「求同存异」。它首先收集所有访问记录中的 XPath 候选（选择每个元素优先级最高的 XPath），然后对所有 XPath 进行规范化处理（去掉索引部分），最后统计出现频率最高的规范化模式。只有当某个模式的出现频率达到阈值（默认 60%）以上时，才认为它是可靠的公共模式。

```python
from autospider.extractor.collector.xpath_extractor import XPathExtractor

extractor = XPathExtractor()

# 从访问记录中提取公共 XPath
common_xpath = extractor.extract_common_xpath(detail_visits)

if common_xpath:
    print(f"发现的公共 XPath: {common_xpath}")
    # 例如: //section//ul/li/a
```

### 页面工具函数

page_utils.py 提供了一系列页面操作的工具函数，这些函数封装了常见的页面交互逻辑，便于在各种处理器中使用。

is_at_page_bottom 函数检测当前页面是否已经滚动到底部。它通过比较页面滚动位置和页面总高度来判断距离底部的距离，当距离小于阈值时认为已到达底部。这个函数在翻页操作和全页面滚动场景中非常有用。

```python
from autospider.extractor.collector.page_utils import is_at_page_bottom, smart_scroll

# 检测是否到达页面底部
is_bottom = await is_at_page_bottom(page, threshold=50)

# 智能滚动（如果已到底部则不滚动）
success = await smart_scroll(page, distance=500)
if not success:
    print("页面已到达底部，无需继续滚动")
```

smart_scroll 函数是智能滚动的实现，它会先检查页面是否已到底部，如果未到底部则执行滚动操作，否则返回失败。这个设计避免了无效的滚动操作，节省了时间和资源。

## LLM 组件

### TaskPlanner

TaskPlanner 是任务规划器，负责在执行前分析任务并生成详细的执行计划。它使用 LLM 理解任务的语义，分析目标网页的可能结构，预判可能遇到的挑战，并规划出合理的执行步骤。这种前置规划能力使得后续的页面导航和数据提取更加有条理和高效。

TaskPlanner 的输入包括起始 URL、任务描述和目标文本。通过渲染 Prompt 模板，将这些信息结构化地传递给 LLM。LLM 分析后会返回任务分析结果、执行步骤列表、目标描述、成功标准以及潜在挑战。这些信息不仅指导后续执行，还帮助开发者理解系统对任务的理解是否正确。

```python
from autospider.extractor.llm.planner import TaskPlanner, TaskPlan

planner = TaskPlanner(
    api_key="your-api-key",
    model="gpt-4"
)

plan = await planner.plan(
    start_url="https://example.com",
    task="查找商品价格",
    target_text="价格"
)

print(f"任务分析: {plan.task_analysis}")
print(f"执行步骤: {plan.steps}")
print(f"成功标准: {plan.success_criteria}")
print(f"潜在挑战: {plan.potential_challenges}")
```

### LLMDecider

LLMDecider 是多模态决策器，是 Agent 的核心决策组件。它接收当前页面状态（截图、标注信息、滚动状态等），结合任务目标，决定下一步应该执行什么操作。这个决策过程模拟了人类浏览网页时的思考方式：查看当前页面内容，判断是否找到了目标，决定是点击、滚动还是执行其他操作。

LLMDecider 支持多种操作类型的决策，包括点击元素、滚动页面、输入文本、等待等。为了避免重复操作和无限循环，组件维护了操作历史、滚动计数、页面滚动历史等状态。每次决策后，组件会更新这些状态，确保 Agent 不会陷入死循环。

```python
from autospider.extractor.llm.decider import LLMDecider
from autospider.common.types import ActionType

decider = LLMDecider(
    api_key="your-api-key",
    model="gpt-4",
    history_screenshots=3  # 发送给 LLM 的历史截图数量
)

# 决策下一步操作
action = await decider.decide(
    state=agent_state,
    screenshot_base64=screenshot,
    marks_text="[1] 价格元素 [2] 加入购物车按钮",
    target_found_in_page=False,
    scroll_info=scroll_info
)

print(f"决定执行: {action.action} -> {action.target}")
```

### Prompt 模板引擎

prompt_template.py 实现了一个通用的 Prompt 模板引擎，支持 YAML 格式的模板文件管理。这个引擎具有 Jinja2 优先、降级兼容的特性：如果环境安装了 Jinja2，则支持完整的模板语法（循环、条件、过滤器等）；如果未安装，则自动降级到简单的占位符替换。

模板引擎提供了三个核心函数。load_template_file 加载并缓存 YAML 模板文件，使用 LRU 缓存提升高频调用场景的性能。render_text 渲染一段模板文本，将变量替换到占位符中。render_template 加载 YAML 文件并渲染指定 section，是最常用的接口。

```python
from autospider.extractor.llm.prompt_template import render_template, get_template_sections

# 渲染 system_prompt 部分
system_prompt = render_template(
    "prompts/decider.yaml",
    section="system_prompt"
)

# 渲染 user_prompt 部分并填充变量
user_prompt = render_template(
    "prompts/decider.yaml",
    section="user_prompt",
    variables={
        "task": "查找商品价格",
        "current_url": "https://example.com/product",
        "target_text": "价格"
    }
)

# 获取模板的所有 section
sections = get_template_sections("prompts/decider.yaml")
print(f"可用 sections: {sections}")
```

模板文件的典型结构如下：

```yaml
system_prompt: |
  你是一个网页导航助手，负责根据任务目标决定下一步操作。

user_prompt: |
  当前任务：{{task}}
  当前页面：{{current_url}}
  目标文本：{{target_text}}
  
  请分析页面内容，决定下一步操作。
```

## LangGraph Agent

### SoMAgent

SoMAgent 是基于 LangGraph 的视觉导航 Agent，它将页面导航过程建模为一个状态图，通过图计算的方式协调各个处理步骤。Agent 内部维护一个状态机，每次迭代执行「观察 -> 决策 -> 执行」的循环，直到找到目标或达到最大步数。

SoMAgent 的核心优势在于其透明性和可解释性。由于使用 LangGraph 实现，整个执行过程被清晰地建模为状态图，开发者可以直观地看到每一步的状态变化和决策逻辑。这种设计也便于调试和优化，比如可以轻松地添加新的节点或修改边的条件。

```python
from autospider.extractor.graph.agent import SoMAgent
from autospider.common.types import RunInput

agent = SoMAgent(
    page=page,
    run_input=RunInput(
        start_url="https://example.com",
        task="查找商品价格",
        target_text="价格",
        max_steps=50,
        output_dir="./output"
    )
)

# 运行 Agent
script = await agent.run()

print(f"生成的 XPath 脚本: {script}")
print(f"执行步数: {script.total_steps}")
```

### GraphState

GraphState 是 LangGraph 中用于在节点间传递的状态对象。它包含了 Agent 运行所需的全部信息，包括输入参数（起始 URL、任务描述、目标文本）、运行时状态（当前步数、页面 URL）、观察结果（截图、标注信息、滚动状态）、执行结果（当前动作、动作结果）以及输出产物（沉淀的脚本步骤、提取的文本）。

这种状态设计确保了每个节点都能访问完整的历史信息，同时也能将新的观察和决策结果写入状态，供后续节点使用。状态的所有更新都是不可变的，每次更新都会生成新的状态对象，这保证了状态变化的可追溯性。

```python
from autospider.extractor.graph.agent import GraphState

state: GraphState = {
    "start_url": "https://example.com",
    "task": "查找商品价格",
    "target_text": "价格",
    "max_steps": 50,
    "output_dir": "./output",
    "step_index": 0,
    "page_url": "",
    "page_title": "",
    "screenshot_base64": "",
    "marks_text": "",
    "mark_id_to_xpath": {},
    "scroll_info": None,
    "current_action": None,
    "action_result": None,
    "script_steps": [],
    "done": False,
    "success": False,
    "error": None,
    "fail_count": 0,
    "extracted_text": None
}
```

## 配置选项

Extractor 模块的行为可以通过配置文件进行精细调整。配置项涵盖了 LLM 参数、提取策略、超时控制等多个方面，合理配置这些选项可以显著提升提取的准确性和效率。

### LLM 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| api_key | - | LLM API Key |
| api_base | - | API Base URL |
| model | gpt-4o | 默认模型名称 |
| planner_model | gpt-4o | 任务规划器使用的模型 |
| planner_api_key | - | 规划器专用 API Key |
| temperature | 0.1 | LLM 温度参数 |
| max_tokens | 2000 | 最大输出 token 数 |
| timeout | 60 | API 调用超时时间（秒）|

### 提取配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| min_confidence | 0.6 | XPath 模式最低置信度 |
| max_explore_pages | 10 | 最大探索页面数 |
| screenshot_quality | 80 | 截图质量（1-100）|
| enable_overlay | true | 是否启用 SoM 标注 |
| overlay_visibility | visible | 标注可见性 |

### 代理配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| use_proxy | false | 是否使用代理 |
| proxy_url | - | 代理地址 |
| proxy_rotation | false | 是否轮换代理 |

## 完整配置示例

```yaml
extractor:
  # LLM 配置
  llm:
    api_key: "${OPENAI_API_KEY}"
    api_base: "https://api.openai.com/v1"
    model: "gpt-4o"
    
    # 规划器专用配置
    planner_api_key: null
    planner_api_base: null
    planner_model: "gpt-4o"
    
    # 生成参数
    temperature: 0.1
    max_tokens: 2000
    timeout: 60

  # 提取配置
  extraction:
    # XPath 模式置信度阈值
    min_confidence: 0.6
    
    # 探索阶段配置
    max_explore_pages: 10
    
    # 截图配置
    screenshot_quality: 80
    
    # SoM 标注配置
    enable_overlay: true
    overlay_visibility: "visible"

  # 代理配置
  proxy:
    enabled: false
    url: null
    rotation: false

  # 输出配置
  output:
    dir: "./output"
    save_screenshots: true
    save_marks: true
```

## 高级用法

### 自定义 LLM 客户端

默认情况下，Extractor 使用 LangChain 的 ChatOpenAI 作为 LLM 客户端。对于使用其他 LLM 服务（如 Claude、国产模型等）的场景，可以通过自定义客户端来扩展支持。

```python
from autospider.extractor.llm.decider import LLMDecider
from langchain_openai import ChatOpenAI

# 使用自定义 API Base
decider = LLMDecider(
    api_key="your-api-key",
    api_base="https://api.your-llm.com/v1",
    model="your-model"
)
```

### 自定义 Prompt 模板

Prompt 模板文件位于 prompts 目录下，支持用户自定义修改。通过调整模板内容，可以改变 LLM 的行为模式，使其更适应特定的采集场景。

```yaml
# prompts/decider.yaml
system_prompt: |
  你是一个专业的网页数据采集助手。
  你的任务是分析页面截图和标注，决定下一步操作。
  
  注意事项：
  1. 优先点击包含目标文本的元素
  2. 避免重复点击已经访问过的链接
  3. 页面底部时优先使用分页控件

user_prompt: |
  任务：{{task}}
  目标：{{target_text}}
  
  当前页面元素标注：
  {{marks_text}}
  
  请输出下一步操作。
```

### 多策略 URL 提取

对于复杂的列表页结构，可以组合使用多种 URL 提取策略以提高覆盖率。

```python
from autospider.extractor.collector.url_extractor import URLExtractor

extractor = URLExtractor()

# 策略1：使用 LLM 智能提取
llm_urls = await extractor.extract_with_llm(page, task_description)

# 策略2：使用 XPath 模式提取
xpath_urls = await extractor.extract_with_xpath(page, common_xpath)

# 策略3：使用正则表达式提取
regex_urls = await extractor.extract_with_regex(page, url_pattern)

# 合并结果并去重
all_urls = list(set(llm_urls + xpath_urls + regex_urls))
```

### Agent 状态监控

在长时间运行的 Agent 任务中，可以定期检查状态来实现进度监控和异常处理。

```python
from autospider.extractor.graph.agent import SoMAgent

agent = SoMAgent(page=page, run_input=run_input)

# 运行并监控
task = asyncio.create_task(agent.run())

while not task.done():
    state = agent.get_current_state()
    print(f"当前步数: {state['step_index']}/{state['max_steps']}")
    print(f"当前页面: {state['page_url']}")
    print(f"已沉淀步骤: {len(state['script_steps'])}")
    
    if state.get('error'):
        print(f"错误: {state['error']}")
        break
    
    await asyncio.sleep(1)

result = await task
```

## 最佳实践

使用 Extractor 模块时，有几个重要的最佳实践值得遵循。首先是任务描述的撰写，应该尽量清晰、具体地描述目标数据，这样能帮助 LLM 更准确地理解任务意图。例如，与其说「采集商品信息」，不如说「采集商品名称、价格、详情描述和图片 URL」。

其次是目标文本的选择。目标文本应该是页面上可见的唯一性文本，能够明确标识目标元素的位置。如果目标文本在多个位置出现，可能会导致 LLM 决策时产生混淆。如果无法提供唯一文本，可以考虑使用目标元素的上下文文本作为补充信息。

再次是探索阶段的配置。对于结构复杂的列表页，可以适当增加探索阶段的采样数量（explore_count 参数），以便收集更多样本，提高 XPath 模式发现的准确性。但要注意平衡探索成本和收益，过多的探索会延长整体运行时间。

最后是生成的配置和脚本应该妥善保存。Extractor 生成的配置文件包含了大量有价值的信息，如元素选择器、导航模式、数据字段定义等。这些信息不仅用于本次采集，还可以作为后续维护和优化的参考。建议将配置文件纳入版本控制系统进行管理。