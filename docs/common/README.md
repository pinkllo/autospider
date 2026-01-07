# Common 模块

`common` 模块提供 AutoSpider 项目的基础设施和公共工具，包括配置管理、类型定义、浏览器操作、SoM 标注系统和存储管理。

## 目录结构

```
common/
├── __init__.py              # 模块导出
├── config.py                # 配置管理（Pydantic 模型）
├── types.py                 # 核心数据类型定义
├── browser/                 # 浏览器操作
│   ├── __init__.py
│   ├── actions.py          # 动作执行器
│   └── session.py          # 浏览器会话管理
├── som/                    # Set-of-Mark 标注系统
│   ├── __init__.py
│   ├── api.py              # SoM Python API
│   └── inject.js           # 注入脚本
└── storage/                # 持久化存储
    ├── __init__.py
    ├── persistence.py      # 持久化基类
    └── redis_manager.py    # Redis 管理器
```

---

## config.py - 配置管理

### 概述

使用 Pydantic 的 `BaseModel` 实现类型安全的配置管理，支持环境变量覆盖。所有配置项都有合理的默认值，可以通过 `.env` 文件或环境变量进行自定义。

### 配置类

#### `LLMConfig` - LLM 配置

```python
class LLMConfig(BaseModel):
    api_key: str                      # API Key（从 AIPING_API_KEY 读取）
    api_base: str                     # API 基础路径
    model: str                        # 使用的多模态模型
    planner_model: str | None         # Planner 专用模型（可选）
    planner_api_key: str | None       # Planner API Key
    planner_api_base: str | None      # Planner API Base
    temperature: float = 0.1          # 温度参数
    max_tokens: int = 8192            # 最大 token 数
```

**环境变量**：
- `AIPING_API_KEY` - API Key
- `AIPING_API_BASE` - API 基础路径（默认: `https://api.siliconflow.cn/v1`）
- `AIPING_MODEL` - 模型名称（默认: `Qwen3-VL-235B-A22B-Instruct`）
- `SILICON_PLANNER_MODEL` - Planner 模型（可选）
- `SILICON_PLANNER_API_KEY` - Planner API Key
- `SILICON_PLANNER_API_BASE` - Planner API Base

**使用示例**：

```python
from autospider.common.config import LLMConfig, config

# 方式 1: 使用全局配置
llm_config = config.llm
api_key = llm_config.api_key
model = llm_config.model

# 方式 2: 创建自定义配置
custom_config = LLMConfig(
    api_key="your-api-key",
    api_base="https://api.example.com/v1",
    model="gpt-4-vision",
    temperature=0.2,
    max_tokens=4096
)
```

---

#### `BrowserConfig` - 浏览器配置

```python
class BrowserConfig(BaseModel):
    headless: bool                    # 无头模式
    viewport_width: int              # 视口宽度
    viewport_height: int             # 视口高度
    slow_mo: int                     # 慢动作模式（毫秒）
    timeout_ms: int                  # 步骤超时时间
```

**环境变量**：
- `HEADLESS` - 是否启用无头模式（默认: `false`）
- `VIEWPORT_WIDTH` - 视口宽度（默认: `1280`）
- `VIEWPORT_HEIGHT` - 视口高度（默认: `720`）
- `SLOW_MO` - 慢动作延迟（默认: `0`）
- `STEP_TIMEOUT_MS` - 步骤超时（默认: `30000`）

**使用示例**：

```python
from autospider.common.config import BrowserConfig

# 使用默认值
browser_config = BrowserConfig()

# 自定义配置
custom_browser = BrowserConfig(
    headless=True,
    viewport_width=1920,
    viewport_height=1080,
    slow_mo=100,  # 每个操作延迟 100ms
    timeout_ms=60000
)
```

---

#### `AgentConfig` - Agent 配置

```python
class AgentConfig(BaseModel):
    max_steps: int                   # 最大执行步数
    max_fail_count: int              # 最大失败次数
    screenshot_dir: str              # 截图保存目录
    output_dir: str                  # 输出目录
```

**环境变量**：
- `MAX_STEPS` - 最大步数（默认: `20`）
- `SCREENSHOTS_DIR` - 截图目录（默认: `screenshots`）
- `OUTPUT_DIR` - 输出目录（默认: `output`）

---

#### `RedisConfig` - Redis 配置

```python
class RedisConfig(BaseModel):
    enabled: bool                    # 是否启用 Redis
    host: str                        # Redis 主机
    port: int                        # Redis 端口
    password: str | None             # 密码
    db: int                          # 数据库编号
    key_prefix: str                  # 键前缀（命名空间隔离）
```

**环境变量**：
- `REDIS_ENABLED` - 是否启用（默认: `false`）
- `REDIS_HOST` - 主机地址（默认: `localhost`）
- `REDIS_PORT` - 端口（默认: `6379`）
- `REDIS_PASSWORD` - 密码
- `REDIS_DB` - 数据库编号（默认: `0`）
- `REDIS_KEY_PREFIX` - 键前缀（默认: `autospider:urls`）

**使用示例**：

```python
from autospider.common.config import RedisConfig, config

# 使用全局配置
redis_config = config.redis

# 自定义配置
custom_redis = RedisConfig(
    enabled=True,
    host="redis.example.com",
    port=6380,
    password="your-password",
    db=1,
    key_prefix="myproject:spider"
)

# 连接 Redis
if redis_config.enabled:
    import redis
    client = redis.Redis(
        host=redis_config.host,
        port=redis_config.port,
        password=redis_config.password,
        db=redis_config.db
    )
```

---

#### `URLCollectorConfig` - URL 收集器配置

```python
class URLCollectorConfig(BaseModel):
    # 探索配置
    explore_count: int               # 探索阶段进入的详情页数量
    max_scrolls: int                 # 单页最大滚动次数
    no_new_url_threshold: int        # 连续无新 URL 停止阈值
    target_url_count: int            # 目标 URL 数量
    max_pages: int                   # 最大翻页次数
    
    # 反爬虫配置
    action_delay_base: float         # 基础延迟（秒）
    action_delay_random: float       # 随机延迟范围（秒）
    page_load_delay: float           # 页面加载等待（秒）
    scroll_delay: float              # 滚动延迟（秒）
    debug_delay: bool                # 是否打印延迟调试信息
    
    # mark_id 验证配置
    validate_mark_id: bool           # 是否启用验证
    mark_id_match_threshold: float   # 文本匹配阈值（0-1）
    debug_mark_id_validation: bool   # 是否打印验证调试信息
    max_validation_retries: int      # 最大验证重试次数
    
    # 自适应速率控制
    backoff_factor: float            # 退避因子
    max_backoff_level: int           # 最大降速等级
    credit_recovery_pages: int       # 恢复速度需要的成功页数
```

**环境变量**：
- `EXPLORE_COUNT` - 探索数量（默认: `3`）
- `MAX_SCROLLS` - 最大滚动次数（默认: `5`）
- `NO_NEW_URL_THRESHOLD` - 无新 URL 阈值（默认: `2`）
- `TARGET_URL_COUNT` - 目标 URL 数量（默认: `400`）
- `MAX_PAGES` - 最大页数（默认: `40`）
- `ACTION_DELAY_BASE` - 基础延迟（默认: `1.0`）
- `ACTION_DELAY_RANDOM` - 随机延迟范围（默认: `0.5`）
- `PAGE_LOAD_DELAY` - 页面加载等待（默认: `1.5`）
- `SCROLL_DELAY` - 滚动延迟（默认: `0.5`）
- `DEBUG_DELAY` - 打印延迟调试（默认: `true`）
- `VALIDATE_MARK_ID` - 启用 mark_id 验证（默认: `true`）
- `MARK_ID_MATCH_THRESHOLD` - 匹配阈值（默认: `0.6`）
- `DEBUG_MARK_ID_VALIDATION` - 打印验证调试（默认: `true`）
- `MAX_VALIDATION_RETRIES` - 最大验证重试次数（默认: `1`）
- `BACKOFF_FACTOR` - 退避因子（默认: `1.5`）
- `MAX_BACKOFF_LEVEL` - 最大降速等级（默认: `3`）
- `CREDIT_RECOVERY_PAGES` - 恢复速度需要的成功页数（默认: `5`）

**使用示例**：

```python
from autospider.common.config import URLCollectorConfig, config

# 使用全局配置
url_config = config.url_collector
print(f"探索数量: {url_config.explore_count}")
print(f"基础延迟: {url_config.action_delay_base}s")

# 自定义配置（用于高并发场景）
fast_config = URLCollectorConfig(
    explore_count=5,
    action_delay_base=0.5,
    action_delay_random=0.2,
    page_load_delay=0.8,
    target_url_count=1000,
    max_pages=100
)

# 自定义配置（用于反爬虫严格的网站）
careful_config = URLCollectorConfig(
    explore_count=2,
    action_delay_base=2.0,
    action_delay_random=1.0,
    page_load_delay=3.0,
    backoff_factor=2.0,
    max_backoff_level=5
)
```

---

#### `Config` - 全局配置

```python
class Config(BaseModel):
    llm: LLMConfig
    browser: BrowserConfig
    agent: AgentConfig
    url_collector: URLCollectorConfig
    redis: RedisConfig

    @classmethod
    def load(cls) -> "Config":
        """加载配置"""
        return cls()

    def ensure_dirs(self) -> None:
        """确保输出目录存在"""
        ...
```

**使用示例**：

```python
from autospider.common.config import config

# 加载配置（从环境变量）
cfg = Config.load()

# 确保输出目录存在
cfg.ensure_dirs()

# 访问配置
print(f"LLM 模型: {cfg.llm.model}")
print(f"浏览器视口: {cfg.browser.viewport_width}x{cfg.browser.viewport_height}")
print(f"Redis 启用: {cfg.redis.enabled}")
```

---

## types.py - 核心数据类型定义

### 概述

定义了整个项目使用的核心数据类型，包括 SoM 标注、动作定义、LangGraph 状态等。

### 输入参数类型

#### `RunInput` - Agent 运行输入参数

```python
class RunInput(BaseModel):
    start_url: str           # 起始 URL
    task: str                # 任务描述（自然语言）
    target_text: str         # 提取目标文本
    max_steps: int = 20      # 最大执行步数
    headless: bool = False   # 无头模式
    output_dir: str = "output"  # 输出目录
```

**使用示例**：

```python
from autospider.common.types import RunInput

input_data = RunInput(
    start_url="https://example.com",
    task="点击登录按钮，输入用户名和密码",
    target_text="欢迎回来",
    max_steps=30,
    headless=True
)
```

---

### SoM 标注相关类型

#### `BoundingBox` - 元素边界框

```python
class BoundingBox(BaseModel):
    x: float                 # 左上角 x 坐标
    y: float                 # 左上角 y 坐标
    width: float             # 宽度
    height: float            # 高度

    @property
    def center(self) -> tuple[float, float]:
        """返回归一化中心坐标（用于 LLM 辅助校验）"""
        return (self.x + self.width / 2, self.y + self.height / 2)
```

**使用示例**：

```python
bbox = BoundingBox(x=100, y=200, width=50, height=30)
center_x, center_y = bbox.center  # (125.0, 215.0)
```

---

#### `XPathCandidate` - XPath 候选项

```python
class XPathCandidate(BaseModel):
    xpath: str               # XPath 表达式
    priority: int            # 优先级（1=最稳定, 5=最脆弱）
    strategy: str            # 生成策略（id/testid/aria/text/relative）
    confidence: float = 1.0  # 唯一性置信度
```

**策略说明**：
- `id` - 使用 id 属性（最稳定）
- `testid` - 使用 data-testid 属性
- `aria` - 使用 aria-label 属性
- `text` - 使用文本内容
- `relative` - 相对路径（最脆弱）

---

#### `ElementMark` - SoM 标注的元素

```python
class ElementMark(BaseModel):
    mark_id: int                         # 数字编号（截图上显示）
    tag: str                             # HTML 标签名
    role: str | None = None              # ARIA role
    text: str = ""                       # 可见文本
    aria_label: str | None = None        # aria-label
    placeholder: str | None = None       # placeholder
    href: str | None = None              # 链接地址
    input_type: str | None = None        # input 类型
    bbox: BoundingBox                    # 边界框
    center_normalized: tuple[float, float]  # 归一化中心坐标 (0-1)
    xpath_candidates: list[XPathCandidate]  # XPath 候选列表
    is_visible: bool = True              # 是否可见
    z_index: int = 0                     # Z 轴层级
```

**使用示例**：

```python
mark = ElementMark(
    mark_id=5,
    tag="button",
    role="button",
    text="提交",
    aria_label="提交表单",
    bbox=BoundingBox(x=100, y=200, width=80, height=40),
    center_normalized=(0.5, 0.5),
    xpath_candidates=[
        XPathCandidate(xpath="//button[@id='submit']", priority=1, strategy="id"),
        XPathCandidate(xpath="//button[text()='提交']", priority=4, strategy="text"),
    ],
    is_visible=True,
    z_index=1
)
```

---

#### `ScrollInfo` - 页面滚动状态

```python
class ScrollInfo(BaseModel):
    scroll_top: int          # 当前滚动位置（像素）
          # 页面总高度（像素）
    client_height scroll_height: int: int       # 可视区域高度（像素）
    scroll_percent: int      # 滚动百分比 0-100
    is_at_top: bool          # 是否在页面顶部
    is_at_bottom: bool       # 是否在页面底部
    can_scroll_down: bool    # 是否可以向下滚动
    can_scroll_up: bool      # 是否可以向上滚动
```

---

#### `SoMSnapshot` - SoM 快照

```python
class SoMSnapshot(BaseModel):
    url: str                              # 当前 URL
    title: str                            # 页面标题
    viewport_width: int                   # 视口宽度
    viewport_height: int                  # 视口高度
    marks: list[ElementMark]              # 标注元素列表
    screenshot_base64: str = ""           # 带标注的截图（Base64）
    timestamp: float                      # 时间戳
    scroll_info: ScrollInfo | None = None # 滚动状态
```

**使用示例**：

```python
from autospider.common.types import SoMSnapshot, ElementMark

snapshot = SoMSnapshot(
    url="https://example.com",
    title="Example",
    viewport_width=1280,
    viewport_height=720,
    marks=[mark1, mark2, mark3],  # ElementMark 列表
    timestamp=1234567890.123,
    scroll_info=ScrollInfo(
        scroll_top=500,
        scroll_height=2000,
        client_height=720,
        scroll_percent=25,
        is_at_top=False,
        is_at_bottom=False,
        can_scroll_down=True,
        can_scroll_up=True
    )
)

# 遍历所有标注
for mark in snapshot.marks:
    print(f"[{mark.mark_id}] {mark.tag}: {mark.text}")
```

---

### 动作定义类型

#### `ActionType` - 动作类型枚举

```python
class ActionType(str, Enum):
    CLICK = "click"           # 点击
    TYPE = "type"             # 输入
    PRESS = "press"           # 按键
    SCROLL = "scroll"         # 滚动
    NAVIGATE = "navigate"     # 导航
    WAIT = "wait"             # 等待
    EXTRACT = "extract"       # 提取
    GO_BACK = "go_back"       # 返回上一页
    DONE = "done"             # 完成
    RETRY = "retry"           # 重试
```

---

#### `Action` - LLM 输出的动作

```python
class Action(BaseModel):
    action: ActionType                  # 动作类型
    mark_id: int | None = None          # 目标元素编号
    target_text: str | None = None      # 目标文本（用于校验）
    text: str | None = None             # 输入文本
    key: str | None = None              # 按键名称
    url: str | None = None              # 导航 URL
    scroll_delta: tuple[int, int] | None = None  # 滚动量 (dx, dy)
    timeout_ms: int = 5000              # 等待超时
    thinking: str = ""                  # LLM 决策推理过程
    expectation: str | None = None      # 预期结果
```

**使用示例**：

```python
from autospider.common.types import Action, ActionType

# 点击动作
click_action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    thinking="需要点击登录按钮来提交表单"
)

# 输入动作
type_action = Action(
    action=ActionType.TYPE,
    mark_id=3,
    text="myusername",
    target_text="用户名输入框",
    thinking="在用户名输入框中输入用户名"
)

# 滚动动作
scroll_action = Action(
    action=ActionType.SCROLL,
    scroll_delta=(0, 300),
    thinking="向下滚动查看更多内容"
)

# 导航动作
navigate_action = Action(
    action=ActionType.NAVIGATE,
    url="https://example.com/login",
    thinking="导航到登录页面"
)
```

---

#### `ActionResult` - 动作执行结果

```python
class ActionResult(BaseModel):
    success: bool                       # 是否成功
    error: str | None = None            # 错误信息
    new_url: str | None = None          # 新 URL（导航后）
    extracted_text: str | None = None   # 提取的文本
    screenshot_path: str | None = None  # 截图路径
```

---

### XPath 脚本类型

#### `ScriptStepType` - 脚本步骤类型枚举

```python
class ScriptStepType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    PRESS = "press"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    EXTRACT = "extract"
```

---

#### `ScriptStep` - XPath 脚本步骤

```python
class ScriptStep(BaseModel):
    step: int                                      # 步骤序号
    action: ScriptStepType                         # 动作类型
    target_xpath: str | None = None                # 目标元素 XPath
    xpath_alternatives: list[str] = []             # 备选 XPath 列表
    value: str | None = None                       # 输入值
    key: str | None = None                         # 按键
    url: str | None = None                         # 导航 URL
    scroll_delta: tuple[int, int] | None = None    # 滚动量
    wait_condition: str | None = None              # 等待条件
    timeout_ms: int = 5000                         # 超时时间
    description: str = ""                          # 步骤描述
    screenshot_context: str | None = None          # 截图路径
```

---

#### `XPathScript` - 完整的 XPath 脚本

```python
class XPathScript(BaseModel):
    task: str                              # 原始任务描述
    start_url: str                         # 起始 URL
    target_text: str                       # 提取目标
    steps: list[ScriptStep]                # 步骤列表
    extracted_result: str | None = None    # 最终提取结果
    variables: dict[str, str] = {}         # 变量定义
    created_at: str = ""                   # 创建时间
```

**使用示例**：

```python
from autospider.common.types import (
    XPathScript, ScriptStep, ScriptStepType
)

script = XPathScript(
    task="登录并查看订单",
    start_url="https://example.com",
    target_text="订单列表",
    steps=[
        ScriptStep(
            step=1,
            action=ScriptStepType.NAVIGATE,
            url="https://example.com/login",
            description="导航到登录页面"
        ),
        ScriptStep(
            step=2,
            action=ScriptStepType.TYPE,
            target_xpath="//input[@name='username']",
            value="${USERNAME}",
            description="输入用户名"
        ),
        ScriptStep(
            step=3,
            action=ScriptStepType.CLICK,
            target_xpath="//button[@type='submit']",
            description="点击登录按钮"
        ),
    ],
    variables={"USERNAME": "admin"},
    created_at="2024-01-01 12:00:00"
)

# 保存脚本
script.model_dump_json(indent=2)
```

---

### LangGraph 状态类型

#### `AgentState` - Agent 状态

```python
class AgentState(BaseModel):
    input: RunInput                                   # 输入参数
    step_index: int = 0                               # 当前步数
    page_url: str = ""                                # 当前页面 URL
    page_title: str = ""                              # 当前页面标题
    current_snapshot: SoMSnapshot | None = None       # 当前快照
    mark_id_to_xpath: dict[int, list[str]] = {}       # mark_id -> XPath 映射
    last_action: Action | None = None                 # 上一个动作
    last_result: ActionResult | None = None           # 上一个结果
    action_history: list[tuple[Action, ActionResult]] = []  # 动作历史
    script_steps: list[ScriptStep] = []               # 沉淀的脚本步骤
    done: bool = False                                # 是否完成
    success: bool = False                             # 是否成功
    error: str | None = None                          # 错误信息
    fail_count: int = 0                               # 失败次数
    max_fail_count: int = 3                           # 最大失败次数
```

**使用示例**：

```python
from autospider.common.types import AgentState, RunInput

state = AgentState(
    input=RunInput(
        start_url="https://example.com",
        task="收集招标信息",
        target_text="招标结果"
    ),
    step_index=5,
    page_url="https://example.com/page2",
    page_title="Page 2",
    script_steps=[step1, step2, step3],
    action_history=[
        (action1, result1),
        (action2, result2),
    ]
)

# 添加新动作
state.last_action = new_action
state.last_result = new_result
state.action_history.append((new_action, new_result))
state.step_index += 1
```

---

## browser/ - 浏览器操作模块

### actions.py - 动作执行器

#### `ActionExecutor` - 动作执行器

负责执行 LLM 输出的动作，并将其沉淀为可复用的 XPath 脚本。

```python
class ActionExecutor:
    def __init__(self, page: Page):
        """初始化执行器
        
        Args:
            page: Playwright Page 对象
        """
        self.page = page

    async def execute(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行动作
        
        Args:
            action: 要执行的动作
            mark_id_to_xpath: mark_id 到 XPath 列表的映射
            step_index: 当前步骤索引
            
        Returns:
            (执行结果, 脚本步骤)
        """
        ...
```

**支持的 ActionType**：

| ActionType | 说明 | 关键参数 |
|------------|------|----------|
| `CLICK` | 点击元素 | `mark_id` |
| `TYPE` | 输入文本 | `mark_id`, `text` |
| `PRESS` | 按键 | `key`, `mark_id`（可选） |
| `SCROLL` | 滚动 | `scroll_delta` |
| `NAVIGATE` | 导航 | `url` |
| `WAIT` | 等待 | `timeout_ms` |
| `EXTRACT` | 提取文本 | `mark_id`, `target_text` |
| `GO_BACK` | 返回上一页 | 无 |
| `DONE` | 完成任务 | 无 |
| `RETRY` | 重试当前步骤 | 无 |

**使用示例**：

```python
from playwright.async_api import async_playwright
from autospider.common.types import Action, ActionType, ActionExecutor

async def execute_actions():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://example.com")
        
        executor = ActionExecutor(page)
        
        # 执行点击
        click_action = Action(
            action=ActionType.CLICK,
            mark_id=5,
            target_text="登录按钮"
        )
        result, script_step = await executor.execute(
            click_action,
            {5: ["//button[@id='login']", "//button[text()='登录']"]},
            1
        )
        
        print(f"点击成功: {result.success}")
        if script_step:
            print(f"生成的脚本步骤: {script_step.model_dump_json()}")
        
        await browser.close()
```

---

### session.py - 浏览器会话管理

#### `BrowserSession` - 浏览器会话管理器

```python
class BrowserSession:
    def __init__(
        self,
        headless: bool | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        slow_mo: int | None = None,
    ):
        """初始化会话管理器
        
        Args:
            headless: 是否无头模式（默认使用 config 配置）
            viewport_width: 视口宽度
            viewport_height: 视口高度
            slow_mo: 慢动作延迟（毫秒）
        """
        ...

    async def start(self) -> Page:
        """启动浏览器并返回 Page"""
        ...

    async def stop(self) -> None:
        """关闭浏览器"""
        ...

    @property
    def page(self) -> Page | None:
        """获取当前 Page"""
        ...

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """导航到指定 URL
        
        Args:
            url: 目标 URL
            wait_until: 等待策略（load/domcontentloaded/networkidle）
        """
        ...

    async def wait_for_stable(self, timeout_ms: int = 3000) -> None:
        """等待页面稳定（网络空闲）
        
        Args:
            timeout_ms: 超时时间（毫秒）
        """
        ...
```

**使用示例**：

```python
from autospider.common.browser.session import BrowserSession, create_browser_session

# 方式 1: 使用上下文管理器（推荐）
async def example1():
    async with create_browser_session(
        headless=True,
        viewport_width=1920,
        viewport_height=1080
    ) as session:
        page = session.page
        await session.navigate("https://example.com")
        await session.wait_for_stable()
        
        # 执行其他操作...
        title = await page.title()
        print(f"页面标题: {title}")

# 方式 2: 手动管理生命周期
async def example2():
    session = BrowserSession(headless=False)
    try:
        page = await session.start()
        await session.navigate("https://example.com")
        
        # 执行爬取操作...
        
    finally:
        await session.stop()

# 方式 3: 自定义配置
async def example3():
    session = BrowserSession(
        headless=True,
        viewport_width=1280,
        viewport_height=720,
        slow_mo=100  # 每个操作延迟 100ms
    )
    page = await session.start()
    # 使用 page 执行操作...
    await session.stop()
```

---

## som/ - Set-of-Mark 标注系统

### api.py - SoM Python API

提供 Set-of-Mark 标注的核心 API。

#### `inject_and_scan()` - 注入并扫描页面

```python
async def inject_and_scan(page: "Page") -> SoMSnapshot:
    """注入 SoM 脚本并扫描页面
    
    Args:
        page: Playwright Page 对象
        
    Returns:
        SoMSnapshot: 带有标注的快照
    """
```

**功能说明**：
- 注入 JavaScript 脚本到页面
- 扫描所有可交互元素
- 生成唯一标识符（mark_id）
- 计算 XPath 候选（按稳定性排序）
- 检测元素可见性（Z-index 遮挡、视口检测）

**使用示例**：

```python
from autospider.common.som.api import inject_and_scan, build_mark_id_to_xpath_map

async def scan_page(page):
    # 注入并扫描页面
    snapshot = await inject_and_scan(page)
    
    print(f"当前 URL: {snapshot.url}")
    print(f"页面标题: {snapshot.title}")
    print(f"发现 {len(snapshot.marks)} 个可交互元素")
    
    # 打印所有标注
    for mark in snapshot.marks:
        print(f"[{mark.mark_id}] {mark.tag}: {mark.text}")
    
    # 构建 mark_id 到 XPath 的映射
    xpath_map = build_mark_id_to_xpath_map(snapshot)
    print(f"XPath 映射: {xpath_map}")
    
    return snapshot
```

---

#### `capture_screenshot_with_marks()` - 带标注的截图

```python
async def capture_screenshot_with_marks(page: "Page") -> tuple[bytes, str]:
    """截图（包含 SoM 标注框）
    
    Returns:
        (screenshot_bytes, base64_encoded)
    """
```

**使用示例**：

```python
from autospider.common.som.api import capture_screenshot_with_marks

async def take_screenshot(page, path="screenshot.png"):
    screenshot_bytes, base64_str = await capture_screenshot_with_marks(page)
    
    # 保存到文件
    with open(path, "wb") as f:
        f.write(screenshot_bytes)
    
    # 使用 base64_str 发送给 LLM
    return base64_str
```

---

#### `clear_overlay()` - 清除覆盖层

```python
async def clear_overlay(page: "Page") -> None:
    """清除 SoM 覆盖层"""
```

---

#### `set_overlay_visibility()` - 设置覆盖层可见性

```python
async def set_overlay_visibility(page: "Page", visible: bool) -> None:
    """设置覆盖层可见性
    
    Args:
        visible: True 显示，False 隐藏
    """
```

---

#### `get_element_by_mark_id()` - 根据 mark_id 获取元素

```python
async def get_element_by_mark_id(page: "Page", mark_id: int):
    """根据 mark_id 获取元素定位器
    
    Returns:
        Playwright Locator
    """
```

**使用示例**：

```python
from autospider.common.som.api import get_element_by_mark_id

async def click_by_mark_id(page, mark_id):
    locator = await get_element_by_mark_id(page, mark_id)
    await locator.click()
```

---

#### `build_mark_id_to_xpath_map()` - 构建映射

```python
def build_mark_id_to_xpath_map(snapshot: SoMSnapshot) -> dict[int, list[str]]:
    """构建 mark_id 到 xpath 列表的映射
    
    Returns:
        映射字典，xpath 列表按稳定性排序
    """
```

**使用示例**：

```python
from autospider.common.som.api import build_mark_id_to_xpath_map

# 扫描页面
snapshot = await inject_and_scan(page)

# 构建映射
xpath_map = build_mark_id_to_xpath_map(snapshot)

# 结果示例：
# {
#     1: ["//*[@id='nav']", "//nav"],
#     2: ["//*[@data-som-id='2']", "//a[text()='首页']"],
#     3: ["//button[@type='submit']", "//button[contains(@class,'btn-primary')]"]
# }
```

---

#### `format_marks_for_llm()` - 格式化标注信息

```python
def format_marks_for_llm(snapshot: SoMSnapshot, max_marks: int = 50) -> str:
    """格式化 marks 信息供 LLM 使用
    
    Args:
        snapshot: SoMSnapshot
        max_marks: 最大显示的标注数量
        
    Returns:
        紧凑的文本格式
    """
```

**输出格式示例**：

```
[1] div role=navigation @ (0.10,0.15)
[2] a "首页" href=/home @ (0.12,0.18)
[3] button "搜索" type=button @ (0.85,0.05)
[4] input placeholder=输入关键词... @ (0.50,0.10)
...
```

---

### inject.js - 注入脚本

SoM 标注的核心 JavaScript 代码，在页面中执行以下功能：

1. **元素检测**：识别所有可交互元素（a, button, input, select, textarea 等）
2. **边界框计算**：计算元素在视口中的位置和尺寸
3. **可见性校验**：
   - 视口检测（元素是否在可视区域内）
   - Z-index 遮挡分析（检测元素是否被其他元素遮挡）
   - 多点采样验证（确保元素真正可见）
4. **XPath 生成**：按优先级生成稳定的 XPath：
   - `id` - 最稳定
   - `testid` - data-testid 属性
   - `aria` - aria-label/aria-id
   - `text` - 文本内容
   - `relative` - 相对路径
5. **标注覆盖**：在页面上绘制带数字的矩形框

---

## storage/ - 持久化存储模块

### redis_manager.py - Redis 管理器

#### `RedisManager` - Redis 存储管理器

```python
class RedisManager:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        db: int = 0,
        key_prefix: str = "autospider:urls",
    ):
        """初始化 Redis 管理器
        
        Args:
            host: Redis 主机
            port: 端口
            password: 密码
            db: 数据库编号
            key_prefix: 键前缀（命名空间）
        """
        ...

    async def connect(self) -> None:
        """建立 Redis 连接"""
        ...

    async def disconnect(self) -> None:
        """断开连接"""
        ...

    async def save_state(self, key: str, state: dict) -> None:
        """保存状态
        
        Args:
            key: 状态键名
            state: 状态数据
        """
        ...

    async def load_state(self, key: str) -> dict | None:
        """加载状态
        
        Args:
            key: 状态键名
            
        Returns:
            状态数据，不存在返回 None
        """
        ...

    async def delete_state(self, key: str) -> None:
        """删除状态"""
        ...

    async def exists(self, key: str) -> bool:
        """检查状态是否存在"""
        ...

    async def save_collected_urls(self, urls: list[str]) -> None:
        """保存已收集的 URL 列表"""
        ...

    async def load_collected_urls(self) -> list[str]:
        """加载已收集的 URL 列表
        
        Returns:
            URL 列表
        """
        ...

    async def add_url(self, url: str) -> bool:
        """添加单个 URL（去重）
        
        Returns:
            True 表示新添加，False 表示已存在
        """
        ...

    async def get_url_count(self) -> int:
        """获取已收集的 URL 数量"""
        ...

    async def save_page_state(self, page_num: int, state: dict) -> None:
        """保存页面状态（用于断点续传）"""
        ...

    async def load_page_state(self, page_num: int) -> dict | None:
        """加载页面状态"""
        ...

    async def get_last_processed_page(self) -> int | None:
        """获取最后处理的页码"""
        ...
```

**使用示例**：

```python
from autospider.common.storage.redis_manager import RedisManager

async def redis_example():
    # 创建管理器
    manager = RedisManager(
        host="localhost",
        port=6379,
        password=None,
        db=0,
        key_prefix="myproject:spider"
    )
    
    # 连接
    await manager.connect()
    
    # 保存状态
    await manager.save_state("task_1", {
        "page": 5,
        "urls": ["url1", "url2", "url3"],
        "timestamp": "2024-01-01"
    })
    
    # 加载状态
    state = await manager.load_state("task_1")
    print(f"状态: {state}")
    
    # 添加 URL（自动去重）
    await manager.add_url("https://example.com/page1")
    await manager.add_url("https://example.com/page2")
    
    count = await manager.get_url_count()
    print(f"已收集 {count} 个 URL")
    
    # 断开连接
    await manager.disconnect()
```

**与全局配置集成**：

```python
from autospider.common.config import config

if config.redis.enabled:
    manager = RedisManager(
        host=config.redis.host,
        port=config.redis.port,
        password=config.redis.password,
        db=config.redis.db,
        key_prefix=config.redis.key_prefix
    )
    await manager.connect()
```

---

### persistence.py - 持久化基类

提供通用的持久化接口规范。

```python
class PersistenceBase:
    """持久化基类（抽象类）"""
    
    async def save(self, key: str, data: dict) -> None:
        """保存数据"""
        ...
    
    async def load(self, key: str) -> dict | None:
        """加载数据"""
        ...
    
    async def delete(self, key: str) -> None:
        """删除数据"""
        ...
    
    async def exists(self, key: str) -> bool:
        """检查是否存在"""
        ...
```

---

## 模块导出

### `__init__.py`

```python
from .config import Config, config
from .types import Types

__all__ = ["Config", "config", "Types"]
```

**使用示例**：

```python
from autospider.common import config, Config

# 使用全局配置实例
print(config.llm.model)

# 创建新的配置实例
custom_config = Config.load()
```
