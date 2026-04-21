"""配置管理"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

_DOTENV_LOADED = False
_CONFIG_CACHE: "Config | None" = None
REDIS_PIPELINE_MODE = "redis"
PIPELINE_MODE_ONLY_SUPPORTS_REDIS = "pipeline_mode_only_supports_redis"


def _load_environment() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    load_dotenv()
    _DOTENV_LOADED = True


def _env_value(name: str, default: str, *, legacy: str | None = None) -> str:
    value = os.getenv(name)
    if value is None and legacy:
        value = os.getenv(legacy)
    return default if value is None else str(value)


def _env_bool(name: str, default: bool, *, legacy: str | None = None) -> bool:
    fallback = "true" if default else "false"
    return _env_value(name, fallback, legacy=legacy).lower() == "true"


def normalize_pipeline_mode(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return REDIS_PIPELINE_MODE
    if normalized != REDIS_PIPELINE_MODE:
        raise ValueError(PIPELINE_MODE_ONLY_SUPPORTS_REDIS)
    return REDIS_PIPELINE_MODE


class LLMConfig(BaseModel):
    """LLM 配置"""

    api_key: str = Field(default_factory=lambda: os.getenv("BAILIAN_API_KEY", ""))
    api_base: str = Field(
        default_factory=lambda: os.getenv(
            "BAILIAN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    )
    model: str = Field(default_factory=lambda: os.getenv("BAILIAN_MODEL", "qwen3.5-plus"))
    # Planner 专用模型配置（可选，默认使用主模型）
    planner_model: str | None = Field(
        default_factory=lambda: os.getenv("SILICON_PLANNER_MODEL", None)
    )
    planner_api_key: str | None = Field(
        default_factory=lambda: os.getenv("SILICON_PLANNER_API_KEY", None)
    )
    planner_api_base: str | None = Field(
        default_factory=lambda: os.getenv("SILICON_PLANNER_API_BASE", None)
    )
    trace_enabled: bool = Field(
        default_factory=lambda: os.getenv("LLM_TRACE_ENABLED", "true").lower() == "true"
    )
    trace_file: str = Field(
        default_factory=lambda: os.getenv("LLM_TRACE_FILE", "output/llm_trace.jsonl")
    )
    trace_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("LLM_TRACE_MAX_CHARS", "20000"))
    )
    enable_thinking: bool = Field(
        default_factory=lambda: os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"
    )
    temperature: float = 0.1
    max_tokens: int = 8192  # 增加 token 限制，避免 JSON 被截断


class BrowserConfig(BaseModel):
    """浏览器配置"""

    headless: bool = Field(default_factory=lambda: os.getenv("HEADLESS", "true").lower() == "true")
    viewport_width: int = Field(default_factory=lambda: int(os.getenv("VIEWPORT_WIDTH", "1280")))
    viewport_height: int = Field(default_factory=lambda: int(os.getenv("VIEWPORT_HEIGHT", "720")))
    slow_mo: int = Field(default_factory=lambda: int(os.getenv("SLOW_MO", "0")))
    timeout_ms: int = Field(default_factory=lambda: int(os.getenv("STEP_TIMEOUT_MS", "30000")))


class AgentConfig(BaseModel):
    """Agent 配置"""

    max_steps: int = Field(default_factory=lambda: int(os.getenv("MAX_STEPS", "20")))
    max_fail_count: int = 3
    screenshot_dir: str = "screenshots"
    output_dir: str = "output"
    skills_dir: str = Field(default_factory=lambda: os.getenv("AUTOSPIDER_SKILLS_DIR", "skills"))


class LoggingConfig(BaseModel):
    """日志配置。"""

    log_level: str = Field(
        default_factory=lambda: _env_value(
            "AUTOSPIDER_LOG_LEVEL",
            "INFO",
            legacy="LOG_LEVEL",
        )
    )
    log_file: str = Field(
        default_factory=lambda: _env_value(
            "AUTOSPIDER_LOG_FILE",
            "output/runtime.log",
            legacy="LOG_FILE",
        )
    )
    show_locals: bool = Field(
        default_factory=lambda: _env_bool(
            "AUTOSPIDER_LOG_SHOW_LOCALS",
            False,
            legacy="LOG_SHOW_LOCALS",
        )
    )
    log_json: bool = Field(
        default_factory=lambda: _env_bool(
            "AUTOSPIDER_LOG_JSON",
            False,
            legacy="LOG_JSON",
        )
    )
    event_prefix: str = Field(
        default_factory=lambda: _env_value(
            "AUTOSPIDER_LOG_EVENT_PREFIX",
            "autospider",
        )
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> str:
        return str(value or "INFO").strip().upper()


class RedisConfig(BaseModel):
    """Redis 配置

    RedisQueueManager 是一个基于 Stream 的可靠消息队列，支持：
    - ACK 确认机制
    - 故障转移（自动捞回超时任务）
    - 多消费者并发（Consumer Group）
    - 自动去重（基于 Hash）

    通过 key_prefix 可以为不同项目或功能设置独立的命名空间。
    """

    enabled: bool = Field(
        default_factory=lambda: os.getenv("REDIS_ENABLED", "false").lower() == "true"
    )
    host: str = Field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    port: int = Field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    password: str | None = Field(default_factory=lambda: os.getenv("REDIS_PASSWORD", None))
    db: int = Field(default_factory=lambda: int(os.getenv("REDIS_DB", "0")))
    # key_prefix: Redis 键的前缀，用于命名空间隔离（如 "autospider:urls"）
    key_prefix: str = Field(
        default_factory=lambda: os.getenv("REDIS_KEY_PREFIX", "autospider:urls")
    )

    # ===== 队列配置 =====
    # 任务超时时间（毫秒），超过此时间未 ACK 的任务会被其他消费者捞回
    task_timeout_ms: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_TASK_TIMEOUT_MS", "300000"))
    )
    # 消费者名称（默认使用主机名+进程ID）
    consumer_name: str | None = Field(
        default_factory=lambda: os.getenv("REDIS_CONSUMER_NAME", None)
    )
    # 是否自动恢复超时任务
    auto_recover: bool = Field(
        default_factory=lambda: os.getenv("REDIS_AUTO_RECOVER", "true").lower() == "true"
    )
    # 每次获取任务的数量
    fetch_batch_size: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_FETCH_BATCH_SIZE", "10"))
    )
    # 阻塞等待时间（毫秒），0 表示非阻塞
    fetch_block_ms: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_FETCH_BLOCK_MS", "5000"))
    )
    # 最大重试次数（失败任务的重试上限）
    max_retries: int = Field(default_factory=lambda: int(os.getenv("REDIS_MAX_RETRIES", "3")))


class GraphCheckpointConfig(BaseModel):
    """LangGraph checkpoint 配置。"""

    enabled: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_CHECKPOINT_ENABLED", "false").lower() == "true"
    )
    backend: str = Field(default_factory=lambda: os.getenv("GRAPH_CHECKPOINT_BACKEND", "redis"))
    redis_url: str = Field(default_factory=lambda: os.getenv("GRAPH_REDIS_URL", ""))
    host: str = Field(
        default_factory=lambda: os.getenv("GRAPH_REDIS_HOST", os.getenv("REDIS_HOST", "localhost"))
    )
    port: int = Field(
        default_factory=lambda: int(os.getenv("GRAPH_REDIS_PORT", os.getenv("REDIS_PORT", "6379")))
    )
    password: str | None = Field(
        default_factory=lambda: os.getenv("GRAPH_REDIS_PASSWORD", os.getenv("REDIS_PASSWORD", None))
    )
    db: int = Field(default_factory=lambda: int(os.getenv("GRAPH_REDIS_DB", "1")))
    recursion_limit: int = Field(
        default_factory=lambda: int(os.getenv("GRAPH_RECURSION_LIMIT", "128"))
    )


class URLCollectorConfig(BaseModel):
    """URL 收集器配置"""

    # 探索阶段进入的详情页数量
    explore_count: int = Field(default_factory=lambda: int(os.getenv("EXPLORE_COUNT", "3")))
    # 最大滚动次数（单页）
    max_scrolls: int = Field(default_factory=lambda: int(os.getenv("MAX_SCROLLS", "5")))
    # 连续无新 URL 的滚动次数后停止
    no_new_url_threshold: int = Field(
        default_factory=lambda: int(os.getenv("NO_NEW_URL_THRESHOLD", "2"))
    )
    # 目标 URL 数量（达到后停止收集）
    target_url_count: int = Field(default_factory=lambda: int(os.getenv("TARGET_URL_COUNT", "400")))
    # 最大翻页次数（分页收集）
    max_pages: int = Field(default_factory=lambda: int(os.getenv("MAX_PAGES", "40")))

    # ===== 爬取间隔配置（反爬虫） =====
    # 页面操作基础延迟（秒）
    action_delay_base: float = Field(
        default_factory=lambda: float(os.getenv("ACTION_DELAY_BASE", "1.0"))
    )
    # 页面操作延迟随机波动范围（秒）
    action_delay_random: float = Field(
        default_factory=lambda: float(os.getenv("ACTION_DELAY_RANDOM", "0.5"))
    )
    # 页面加载等待时间（秒）
    page_load_delay: float = Field(
        default_factory=lambda: float(os.getenv("PAGE_LOAD_DELAY", "1.5"))
    )
    # 滚动操作延迟（秒）
    scroll_delay: float = Field(default_factory=lambda: float(os.getenv("SCROLL_DELAY", "0.5")))
    # 调试：打印延迟信息
    debug_delay: bool = Field(
        default_factory=lambda: os.getenv("DEBUG_DELAY", "true").lower() == "true"
    )

    # ===== mark_id 验证配置 =====
    # 是否启用 mark_id 与文本的验证
    validate_mark_id: bool = Field(
        default_factory=lambda: os.getenv("VALIDATE_MARK_ID", "true").lower() == "true"
    )
    # 文本匹配相似度阈值（0-1，使用模糊匹配）
    mark_id_match_threshold: float = Field(
        default_factory=lambda: float(os.getenv("MARK_ID_MATCH_THRESHOLD", "0.6"))
    )
    # 调试：打印验证信息
    debug_mark_id_validation: bool = Field(
        default_factory=lambda: os.getenv("DEBUG_MARK_ID_VALIDATION", "true").lower() == "true"
    )
    # 验证失败后的最大重试次数（将反馈给 LLM 重新选择）
    max_validation_retries: int = Field(
        default_factory=lambda: int(os.getenv("MAX_VALIDATION_RETRIES", "1"))
    )

    # ===== 自适应速率控制配置（反爬虫） =====
    # 退避因子（遭遇反爬时延迟倍增因子）
    backoff_factor: float = Field(default_factory=lambda: float(os.getenv("BACKOFF_FACTOR", "1.5")))
    # 最大降速等级
    max_backoff_level: int = Field(default_factory=lambda: int(os.getenv("MAX_BACKOFF_LEVEL", "3")))
    # 连续成功多少页后恢复一级速度
    credit_recovery_pages: int = Field(
        default_factory=lambda: int(os.getenv("CREDIT_RECOVERY_PAGES", "5"))
    )


class FieldExtractorConfig(BaseModel):
    """字段提取器配置"""

    # 探索阶段的 URL 数量
    explore_count: int = Field(default_factory=lambda: int(os.getenv("FIELD_EXPLORE_COUNT", "3")))
    # 校验阶段的 URL 数量
    validate_count: int = Field(default_factory=lambda: int(os.getenv("FIELD_VALIDATE_COUNT", "4")))
    # 导航最大步数
    max_nav_steps: int = Field(default_factory=lambda: int(os.getenv("FIELD_MAX_NAV_STEPS", "20")))
    # 模糊匹配阈值
    fuzzy_match_threshold: float = Field(
        default_factory=lambda: float(os.getenv("FIELD_FUZZY_THRESHOLD", "0.8"))
    )
    # 批处理必填字段失败后是否启用 LLM 挽救
    batch_salvage_enabled: bool = Field(
        default_factory=lambda: os.getenv("FIELD_BATCH_SALVAGE_ENABLED", "true").lower() == "true"
    )
    # 单个页面最多尝试挽救的必填字段数量
    batch_salvage_max_fields_per_page: int = Field(
        default_factory=lambda: int(os.getenv("FIELD_BATCH_SALVAGE_MAX_FIELDS", "2"))
    )
    # 挽救时 LLM 返回值的最小置信度阈值
    batch_salvage_min_confidence: float = Field(
        default_factory=lambda: float(os.getenv("FIELD_BATCH_SALVAGE_MIN_CONFIDENCE", "0.6"))
    )


class PipelineConfig(BaseModel):
    """Pipeline 配置（仅支持 redis 模式）。"""

    mode: str = Field(default_factory=lambda: os.getenv("PIPELINE_MODE", "redis"))

    # 从队列获取任务的超时时间（秒）
    fetch_timeout_s: float = Field(
        default_factory=lambda: float(os.getenv("PIPELINE_FETCH_TIMEOUT", "5"))
    )

    # 批量获取任务的数量
    batch_fetch_size: int = Field(
        default_factory=lambda: int(os.getenv("PIPELINE_BATCH_FETCH_SIZE", "20"))
    )

    # 批量同步/刷写进度的数量
    batch_flush_size: int = Field(
        default_factory=lambda: int(os.getenv("PIPELINE_BATCH_FLUSH_SIZE", "20"))
    )

    # 详情抽取消费者并发数（每个 worker 使用独立页面）
    consumer_concurrency: int = Field(
        default_factory=lambda: int(os.getenv("PIPELINE_CONSUMER_CONCURRENCY", "3"))
    )
    # 本机调试时可显式开启串行模式：强制将任务并发与消费者并发都压成 1
    local_serial_mode: bool = Field(
        default_factory=lambda: os.getenv("LOCAL_SERIAL_MODE", "false").lower() == "true"
    )

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> str:
        return normalize_pipeline_mode(value)


class PlannerConfig(BaseModel):
    """任务规划器配置（多分类并行采集）"""

    # 同时运行的子任务最大数量（默认 1 = 串行，按需调大以并行）
    max_concurrent_subtasks: int = Field(
        default_factory=lambda: int(os.getenv("PLANNER_MAX_CONCURRENT", "1"))
    )
    # 全局进度文件名
    progress_file: str = Field(
        default_factory=lambda: os.getenv("PLANNER_PROGRESS_FILE", "task_progress.json")
    )
    # 子任务内部详情抽取消费者并发数（默认 1，避免资源过载）
    subtask_consumer_concurrency: int = Field(
        default_factory=lambda: int(os.getenv("PLANNER_SUBTASK_CONSUMER_CONCURRENCY", "1"))
    )
    runtime_subtasks_max_children: int = Field(
        default_factory=lambda: int(os.getenv("PLANNER_RUNTIME_SUBTASKS_MAX_CHILDREN", "0"))
    )
    runtime_subtasks_use_main_model: bool = Field(
        default_factory=lambda: os.getenv(
            "PLANNER_RUNTIME_SUBTASKS_USE_MAIN_MODEL", "false"
        ).lower()
        == "true"
    )


class TaskPlaneConfig(BaseModel):
    """TaskPlane 调度平面配置。"""

    enabled: bool = Field(
        default_factory=lambda: os.getenv("TASKPLANE_ENABLED", "true").lower() == "true"
    )
    store: str = Field(default_factory=lambda: os.getenv("TASKPLANE_STORE", "memory"))
    redis_url: str = Field(
        default_factory=lambda: os.getenv(
            "TASKPLANE_REDIS_URL",
            os.getenv("GRAPH_REDIS_URL", ""),
        )
    )
    redis_namespace: str = Field(
        default_factory=lambda: os.getenv("TASKPLANE_REDIS_NAMESPACE", "taskplane")
    )
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "TASKPLANE_DATABASE_URL",
            os.getenv("DATABASE_URL", ""),
        )
    )

    @field_validator("store", mode="before")
    @classmethod
    def validate_store(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"memory", "redis", "dual"}:
            return normalized
        raise ValueError("taskplane_store_must_be_one_of_memory_redis_dual")


class DatabaseConfig(BaseModel):
    """数据库配置（PostgreSQL）"""

    url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/autospider",
        )
    )
    echo: bool = Field(default_factory=lambda: os.getenv("DB_ECHO", "false").lower() == "true")
    pool_size: int = Field(default_factory=lambda: int(os.getenv("DB_POOL_SIZE", "5")))
    max_overflow: int = Field(default_factory=lambda: int(os.getenv("DB_MAX_OVERFLOW", "10")))


class Config(BaseModel):
    """全局配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    url_collector: URLCollectorConfig = Field(default_factory=URLCollectorConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    graph_checkpoint: GraphCheckpointConfig = Field(default_factory=GraphCheckpointConfig)
    field_extractor: FieldExtractorConfig = Field(default_factory=FieldExtractorConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    taskplane: TaskPlaneConfig = Field(default_factory=TaskPlaneConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    @classmethod
    def load(cls) -> "Config":
        """加载配置"""
        _load_environment()
        return cls()

    def ensure_dirs(self) -> None:
        """确保输出目录存在"""
        Path(self.agent.screenshot_dir).mkdir(parents=True, exist_ok=True)
        Path(self.agent.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.agent.skills_dir).mkdir(parents=True, exist_ok=True)


def get_config(*, reload: bool = False) -> Config:
    global _CONFIG_CACHE
    if reload or _CONFIG_CACHE is None:
        _CONFIG_CACHE = Config.load()
    return _CONFIG_CACHE


class _ConfigProxy:
    def __getattr__(self, name: str):
        return getattr(get_config(), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(get_config(), name, value)


# 全局配置代理（惰性加载）
config = _ConfigProxy()
