"""配置管理"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 加载 .env 文件
load_dotenv()


class LLMConfig(BaseModel):
    """LLM 配置"""

    api_key: str = Field(default_factory=lambda: os.getenv("AIPING_API_KEY", ""))
    api_base: str = Field(
        default_factory=lambda: os.getenv("AIPING_API_BASE", "https://api.siliconflow.cn/v1")
    )
    model: str = Field(default_factory=lambda: os.getenv("AIPING_MODEL", "zai-org/GLM-4.6V"))
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
    temperature: float = 0.1
    max_tokens: int = 8192  # 增加 token 限制，避免 JSON 被截断


class BrowserConfig(BaseModel):
    """浏览器配置"""

    headless: bool = Field(
        default_factory=lambda: os.getenv("HEADLESS", "false").lower() == "true"
    )
    viewport_width: int = Field(
        default_factory=lambda: int(os.getenv("VIEWPORT_WIDTH", "1280"))
    )
    viewport_height: int = Field(
        default_factory=lambda: int(os.getenv("VIEWPORT_HEIGHT", "720"))
    )
    slow_mo: int = Field(default_factory=lambda: int(os.getenv("SLOW_MO", "0")))
    timeout_ms: int = Field(
        default_factory=lambda: int(os.getenv("STEP_TIMEOUT_MS", "30000"))
    )


class AgentConfig(BaseModel):
    """Agent 配置"""

    max_steps: int = Field(default_factory=lambda: int(os.getenv("MAX_STEPS", "20")))
    max_fail_count: int = 3
    screenshot_dir: str = "screenshots"
    output_dir: str = "output"


class URLCollectorConfig(BaseModel):
    """URL 收集器配置"""

    # 探索阶段进入的详情页数量
    explore_count: int = Field(
        default_factory=lambda: int(os.getenv("EXPLORE_COUNT", "3"))
    )
    # 最大滚动次数
    max_scrolls: int = Field(
        default_factory=lambda: int(os.getenv("MAX_SCROLLS", "20"))
    )
    # 连续无新 URL 的滚动次数后停止
    no_new_url_threshold: int = Field(
        default_factory=lambda: int(os.getenv("NO_NEW_URL_THRESHOLD", "3"))
    )
    # 目标 URL 数量（达到后停止收集）
    target_url_count: int = Field(
        default_factory=lambda: int(os.getenv("TARGET_URL_COUNT", "5"))
    )
    # 最大翻页次数（分页收集）
    max_pages: int = Field(
        default_factory=lambda: int(os.getenv("MAX_PAGES", "10"))
    )


class Config(BaseModel):
    """全局配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    url_collector: URLCollectorConfig = Field(default_factory=URLCollectorConfig)

    @classmethod
    def load(cls) -> "Config":
        """加载配置"""
        return cls()

    def ensure_dirs(self) -> None:
        """确保输出目录存在"""
        Path(self.agent.screenshot_dir).mkdir(parents=True, exist_ok=True)
        Path(self.agent.output_dir).mkdir(parents=True, exist_ok=True)


# 全局配置实例
config = Config.load()
